from app.agents.base.state import AgentState
from langgraph.types import Command
from typing import Literal
from app.helpers.utils.common import get_response_llm
from app.core.config import *
import json
from app.helpers.utils.logger import logging
from app.helpers.utils.common import read_json
from langsmith import traceable
from langchain.messages import HumanMessage, AIMessage
from langgraph.graph import END
from app.agents.base.state import StreamEvent
from app.agents.base.utils import emit
import asyncio

@traceable
async def supervisor_node(state: AgentState) -> Command[Literal["qa"]]:
    messages = state["messages"]
    user_input = messages[-1].content
    await emit(StreamEvent(
        type="progress", node="supervisor",
        message="Đang xác định thủ tục của bạn..."
    ))

    prompt = supervisor_prompt["SUPERVISOR_PROMPT_V2"].format(
        query = user_input
    )

    response = get_response_llm(prompt, messages)
    data = json.loads(response)

    procedures = data.get("procedures", [])

    await emit(StreamEvent(
        type="result", node="supervisor",
        message=f"Đã tìm thấy: {procedures}",
        data={"procedures": procedures}
    ))

    name_ids = read_json("app/agents/supervisor", "name_id.json")

    procedure_ids = [name_ids[proc] for proc in procedures if proc in name_ids]    

    return Command(
        goto=data["pipeline"][0],
        update={
            "procedures": procedure_ids,
            "messages": [AIMessage(content=json.dumps(data, ensure_ascii=False))],
            "pipeline": data.get("pipeline", ["qa"]),
            "fields": data.get("fields", [])
        },
    )


    

