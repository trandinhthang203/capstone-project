from functools import lru_cache
from typing import Literal

from langgraph.types import Command
from langsmith import traceable

from app.agents.base.state import AgentState, StreamEvent
from app.agents.base.utils import emit
from app.agents.memory.conversation_memory import maybe_refresh_summary, resolve_followup
from app.agents.supervisor.constants import CONFIDENCE_THRESHOLD
from app.agents.supervisor.helper import _parse_intent_response, _normalize_pipeline, _resolve_first_agent
from app.agents.supervisor.qdrant_retriever import retrieve_procedures
from app.core.config import supervisor_prompt
from app.helpers.utils.common import get_response_llm, read_json
from app.helpers.utils.logger import logging
import asyncio

RETRIEVE_TOP_K = 8         
DEFAULT_QA_FIELDS = [      
    "thu_tuc.ten_thu_tuc", "thu_tuc.trinh_tu_thuc_hien",
    "thu_tuc.doi_tuong_thuc_hien", "thu_tuc.co_quan_thuc_hien",
    "thu_tuc.ket_qua_thuc_hien", "thu_tuc.yeu_cau_dieu_kien",
    "thu_tuc.dia_chi_tiep_nhan_hs",
]


@lru_cache(maxsize=1)
def _name_ids():
    """Cache name_ids.json vĩnh viễn trong process — không đọc file mỗi turn."""
    return read_json("app/agents/supervisor", "name_id.json")


@traceable
async def context_node(state: AgentState) -> Command[Literal["intent_router"]]:
    """
    CHẠY SUMMARY + FOLLOWUP SONG SONG bằng asyncio.gather.
    Chỉ refresh summary khi messages ≥ trigger (đã có sẵn trong memory_module).
    """
    messages = state.get("messages", [])
    raw_user_input = state["user_input"]

    summary_coro = maybe_refresh_summary(
        existing_summary=state.get("conversation_summary", ""),
        messages=messages,
        summarized_upto=state.get("summarized_upto", 0),
    )

    followup_coro = resolve_followup(
        raw_query=raw_user_input,
        messages=messages,
        summary=state.get("conversation_summary", ""),
        last_procedures=state.get("procedure_names", []),
        last_answer=state.get("last_answer", ""),
    )
    (summary, new_summarized_upto), followup = await asyncio.gather(summary_coro, followup_coro)

    resolved = followup.get("standalone_query") or raw_user_input
    logging.info(
        "[context_node] is_followup=%s confidence=%s resolved=%s",
        followup.get("is_followup"), followup.get("confidence"), resolved,
    )

    return Command(
        goto="intent_router",              
        update={
            "conversation_summary": summary,
            "summarized_upto": new_summarized_upto,
            "resolved_user_input": resolved,
            "is_followup": bool(followup.get("is_followup", False)),
        },
    )

@traceable
async def intent_router_node(state: AgentState) -> Command[Literal["qa"]]:
    messages = state["messages"]
    raw_user_input = state["user_input"]
    resolved_user_input = state.get("resolved_user_input") or raw_user_input
    summary = state.get("conversation_summary", "")

    await emit(StreamEvent(type="progress", node="supervisor",
                            message="Đang tra cứu thủ tục liên quan..."))

    # Retrieval
    try:
        candidate_hits = await retrieve_procedures(resolved_user_input, top_k=RETRIEVE_TOP_K)
    except Exception as exc:
        logging.error("[intent_router] Qdrant error: %s", exc, exc_info=True)
        candidate_hits = []

    candidate_names = [h["ten_thu_tuc"] for h in candidate_hits]
    procedures_block = "\n".join(f"- {name}" for name in candidate_names) or "[]"

    await emit(StreamEvent(type="progress", node="supervisor",
                            message="Đang phân tích câu hỏi..."))

    # Prompt hợp nhất kèm danh sách candidate vừa retrieve
    prompt = supervisor_prompt["SUPERVISOR_PROMPT_V3"].format(
        query=resolved_user_input,
        raw_query=raw_user_input,
        procedures=procedures_block,
        last_domain=state.get("domain", "") or "[]",
        last_procedures=", ".join(state.get("procedure_names", []))
                          if state.get("procedure_names") else "[]",
    )

    raw = await get_response_llm(
        prompt=prompt,
        messages=messages,
        summary=summary,
        max_messages=4,
    )
    data = _parse_intent_response(raw)

    intent = data.get("intent", "unclear")
    confidence = float(data.get("confidence", 0.0))
    procedures = data.get("procedures", []) or []
    fields = data.get("fields", []) or DEFAULT_QA_FIELDS
    pipeline = _normalize_pipeline(data.get("pipeline", ["qa"]))

    if confidence < CONFIDENCE_THRESHOLD:
        if state.get("is_followup"):
            intent = "legal"
            confidence = max(confidence, 0.75)
        else:
            intent = "unclear"

    if intent == "legal" and not procedures and state.get("is_followup"):
        procedures = state.get("procedure_names", [])

    # Safety net: chỉ giữ lại thủ tục thực sự nằm trong candidate đã
    # retrieve (hoặc thủ tục turn trước, cho followup) — phòng LLM vẫn bịa
    if procedures:
        valid_names = set(candidate_names) | set(state.get("procedure_names", []))
        procedures = [p for p in procedures if p in valid_names]

    name_ids_map = _name_ids()
    procedure_ids = [name_ids_map[p] for p in procedures if p in name_ids_map]

    logging.info("[intent_router] intent=%s conf=%.2f procs=%s fields=%s",
                 intent, confidence, procedures, len(fields))

    await emit(StreamEvent(type="progress", node="supervisor",
                            message="Đã xác định xong thủ tục."))

    return Command(
        goto="qa",
        update={
            "intent": intent,
            "procedures": procedure_ids,
            "procedure_names": procedures,
            "pipeline": pipeline,
            "fields": fields,
        },
    )