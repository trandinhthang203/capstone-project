from app.agents.base.state import AgentState
from langgraph.types import Command
from typing import Literal
from app.helpers.utils.common import get_response_llm
from app.core.config import *
import json
from app.helpers.utils.logger import logging
from app.helpers.utils.common import read_json
from langsmith import traceable
from langchain.messages import AIMessage
from langgraph.graph import END
from app.agents.base.state import StreamEvent
from app.agents.base.utils import emit
from app.agents.supervisor.constants import DOMAIN_LABELS, CONFIDENCE_THRESHOLD
from app.agents.supervisor.helper import _parse_intent_response, _validate_domain

@traceable
async def intent_node(
    state: AgentState,
) -> Command[Literal["supervisor", "qa"]]:
    messages = state["messages"]
    user_input = state["user_input"]

    await emit(StreamEvent(
        type="progress",
        node="supervisor",
        message="Đang phân tích câu hỏi người dùng...",
    ))

    prompt = supervisor_prompt["INTENT_PROMPT"].format(query=user_input)
    raw = await get_response_llm(prompt, messages) 
    data = _parse_intent_response(raw)

    intent: str = data.get("intent", "unclear")
    domain: str | None = _validate_domain(data.get("domain"))
    confidence: float = float(data.get("confidence", 0.0))

    logging.info(
        f"[intent_node] intent={intent} domain={domain} confidence={confidence:.2f}"
    )

    if confidence < CONFIDENCE_THRESHOLD:
        intent = "unclear"

    domain_label = DOMAIN_LABELS.get(domain, domain or "chưa xác định")
    await emit(StreamEvent(
        type="progress",
        node="supervisor",
        message=f"Câu hỏi thuộc lĩnh vực {domain_label or 'chưa xác định'}",
    ))

    if intent in ("chitchat", "unclear"):
        return Command(
            goto="qa",
            update={
                "intent": intent,
                "domain": domain,
                "intent_confidence": confidence,
            },
        )

    return Command(
        goto="supervisor",
        update={
            "intent": intent,
            "domain": domain,
            "intent_confidence": confidence,
        },
    )

@traceable
async def supervisor_node(state: AgentState) -> Command[Literal["qa"]]:
    messages = state["messages"]
    user_input = state["user_input"]
    domain = state.get("domain")

    await emit(StreamEvent(
        type="progress", 
        node="supervisor",
        message="Đang xác định thủ tục của bạn..."
    ))

    name_ids: dict = read_json("app/agents/supervisor", "name_id.json")
    domain_procedures: dict = read_json("app/agents/supervisor", "domain_procedures.json")

    procedure_names = (
        domain_procedures.get(domain, list(name_ids.keys()))
        if domain
        else list(name_ids.keys())
    )

    prompt = supervisor_prompt["SUPERVISOR_PROMPT_V2"].format(
        query=user_input,
        procedures="\n".join(f"- {name}" for name in procedure_names),
    )

    response = await get_response_llm(prompt, messages)
    data = json.loads(response)

    procedures = data.get("procedures", [])
    procedure_ids = [name_ids[proc] for proc in procedures if proc in name_ids]

    await emit(StreamEvent(
        type="result",
        node="supervisor",
        message=f"Đã tìm thấy: {', '.join(procedures)}",
        data={"procedures": procedures}
    ))

    return Command(
        goto=data["pipeline"][0],
        update={
            "procedures": procedure_ids,
            # "messages": [AIMessage(content=json.dumps(data, ensure_ascii=False))],
            "pipeline": data.get("pipeline", ["qa"]),
            "fields": data.get("fields", [])
        },
    )

    

