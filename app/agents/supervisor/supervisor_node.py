from typing import Literal

from langgraph.types import Command
from langsmith import traceable

from app.agents.base.state import AgentState, StreamEvent
from app.agents.base.utils import emit
from app.agents.memory.conversation_memory import maybe_refresh_summary, resolve_followup
from app.agents.supervisor.constants import DOMAIN_LABELS, CONFIDENCE_THRESHOLD
from app.agents.supervisor.helper import _parse_intent_response, _validate_domain
from app.core.config import supervisor_prompt
from app.helpers.utils.common import get_response_llm, read_json
from app.helpers.utils.logger import logging


def _normalize_pipeline(pipeline: list) -> list[str]:
    flat: list[str] = []

    for item in pipeline or ["qa"]:
        if isinstance(item, str):
            flat.append(item)
        elif isinstance(item, list):
            flat.extend([x for x in item if isinstance(x, str)])

    if not flat:
        flat = ["qa"]

    if flat[0] != "qa":
        flat = ["qa"] + [x for x in flat if x != "qa"]

    return flat


@traceable
async def context_node(state: AgentState) -> Command[Literal["intent"]]:
    messages = state.get("messages", [])
    raw_user_input = state["user_input"]

    summary = await maybe_refresh_summary(
        existing_summary=state.get("conversation_summary", ""),
        messages=messages,
    )

    followup = await resolve_followup(
        raw_query=raw_user_input,
        messages=messages,
        summary=summary,
        last_domain=state.get("last_domain"),
        last_procedures=state.get("procedure_names", []),
        last_answer=state.get("last_answer", ""),
    )

    resolved_user_input = followup.get("standalone_query") or raw_user_input

    logging.info(
        "[context_node] is_followup=%s confidence=%s resolved_user_input=%s",
        followup.get("is_followup"),
        followup.get("confidence"),
        resolved_user_input,
    )

    return Command(
        goto="intent",
        update={
            "conversation_summary": summary,
            "resolved_user_input": resolved_user_input,
            "is_followup": bool(followup.get("is_followup", False)),
            "followup_confidence": float(followup.get("confidence", 0.0)),
            "followup_reason": followup.get("reason", ""),
        },
    )


@traceable
async def intent_node(
    state: AgentState,
) -> Command[Literal["supervisor", "qa"]]:
    messages = state["messages"]
    raw_user_input = state["user_input"]
    resolved_user_input = state.get("resolved_user_input") or raw_user_input
    summary = state.get("conversation_summary", "")

    await emit(StreamEvent(
        type="progress",
        node="supervisor",
        message="Đang phân tích câu hỏi người dùng...",
    ))

    prompt = supervisor_prompt["INTENT_PROMPT_V2"].format(
        query=resolved_user_input,
        raw_query=raw_user_input,
        last_domain=state.get("last_domain") or "null",
        last_procedures=", ".join(state.get("procedure_names", [])) if state.get("procedure_names") else "[]",
        followup_reason=state.get("followup_reason") or "Không có",
    )

    raw = await get_response_llm(
        prompt=prompt,
        messages=messages,
        summary=summary,
        max_messages=6,
    )
    data = _parse_intent_response(raw)

    intent: str = data.get("intent", "unclear")
    domain: str | None = _validate_domain(data.get("domain"))
    confidence: float = float(data.get("confidence", 0.0))

    if confidence < CONFIDENCE_THRESHOLD:
        if state.get("is_followup") and state.get("last_domain"):
            intent = "legal"
            domain = state.get("last_domain")
            confidence = max(confidence, 0.75)
        else:
            intent = "unclear"

    logging.info(
        "[intent_node] intent=%s domain=%s confidence=%.2f raw_query=%s resolved_query=%s",
        intent, domain, confidence, raw_user_input, resolved_user_input
    )

    domain_label = DOMAIN_LABELS.get(domain, domain or "chưa xác định")
    await emit(StreamEvent(
        type="progress",
        node="supervisor",
        message=f"Câu hỏi thuộc lĩnh vực {domain_label}",
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
    raw_user_input = state["user_input"]
    resolved_user_input = state.get("resolved_user_input") or raw_user_input
    summary = state.get("conversation_summary", "")
    domain = state.get("domain")

    await emit(StreamEvent(
        type="progress",
        node="supervisor",
        message="Đang xác định thủ tục của bạn..."
    ))

    name_ids: dict = read_json("app/agents/supervisor", "name_id.json")
    domain_procedures: dict = read_json("app/agents/supervisor", "domain_procedures.json")

    procedure_names_pool = (
        domain_procedures.get(domain, list(name_ids.keys()))
        if domain
        else list(name_ids.keys())
    )

    extra_context = ""
    if state.get("is_followup"):
        extra_context = (
            f"- last_domain: {state.get('last_domain') or 'null'}\n"
            f"- last_procedures: {', '.join(state.get('procedure_names', [])) if state.get('procedure_names') else '[]'}\n"
            f"- followup_reason: {state.get('followup_reason') or 'Không có'}"
        )

    prompt = supervisor_prompt["SUPERVISOR_PROMPT_V3"].format(
        query=resolved_user_input,
        procedures="\n".join(f"- {name}" for name in procedure_names_pool),
        last_domain=state.get("last_domain") or "null",
        last_procedures=", ".join(state.get("procedure_names", [])) if state.get("procedure_names") else "[]",
        followup_reason=state.get("followup_reason") or "Không có",
    )

    response = await get_response_llm(
        prompt=prompt,
        messages=messages,
        summary=summary,
        max_messages=6,
        extra_system_context=extra_context,
    )
    data = _parse_intent_response(response)

    logging.info("[supervisor_node] response=%s", response)

    procedures = data.get("procedures", []) or []
    fields = data.get("fields", []) or []
    pipeline = _normalize_pipeline(data.get("pipeline", ["qa"]))

    if not procedures and state.get("is_followup") and state.get("last_procedures"):
        procedures = state.get("procedure_names", [])
        logging.info("[supervisor_node] inherited previous procedures=%s", procedures)

    if procedures:
        procedure_ids = [name_ids[proc] for proc in procedures if proc in name_ids]

        await emit(StreamEvent(
            type="result",
            node="supervisor",
            message=f"Đã tìm thấy: {', '.join(procedures)}",
            data={"procedures": procedures},
        ))
    else:
        procedure_ids = []

        await emit(StreamEvent(
            type="result",
            node="supervisor",
            message="Không xác định được thủ tục...",
            data={"procedures": procedures},
        ))

    return Command(
        goto="qa",
        update={
            "procedures": procedure_ids,
            "procedure_names": procedures,
            "pipeline": pipeline,
            "fields": fields,
        },
    )
