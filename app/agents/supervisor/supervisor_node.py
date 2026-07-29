<<<<<<< HEAD
from typing import Literal

from langgraph.types import Command
from langsmith import traceable

from app.agents.base.state import AgentState, StreamEvent
from app.agents.base.utils import emit
from app.agents.memory.conversation_memory import maybe_refresh_summary, resolve_followup
from app.agents.supervisor.constants import CONFIDENCE_THRESHOLD
from app.agents.supervisor.helper import _parse_intent_response, _normalize_pipeline, _resolve_first_agent, _format_candidates_for_llm
from app.agents.supervisor.qdrant_retriever import retrieve_procedures
from app.core.config import supervisor_prompt
from app.helpers.utils.common import get_response_llm, read_json
from app.helpers.utils.logger import logging

RETRIEVE_TOP_K = 15


@traceable
async def context_node(state: AgentState) -> Command[Literal["intent"]]:
    """Resolve followup query và làm mới conversation summary."""
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
    """
    Luồng:
      1. Retrieve top-K thủ tục ứng viên từ Qdrant (hybrid dense + BM25/RRF).
      2. LLM phân loại intent dựa trên query (legal / chitchat / unclear).
         Danh sách ứng viên được cache vào state để supervisor_node tái sử dụng.
      3. Route: legal → supervisor_node, còn lại → qa_node.
    """
    messages = state["messages"]
    raw_user_input = state["user_input"]
    resolved_user_input = state.get("resolved_user_input") or raw_user_input
    summary = state.get("conversation_summary", "")

    await emit(StreamEvent(
        type="progress",
        node="supervisor",
        message="Đang phân tích câu hỏi người dùng...",
    ))

    # ── Bước 1: Qdrant hybrid retrieve ──────────────────────────────
    candidate_hits = await retrieve_procedures(
        query=resolved_user_input,
        top_k=RETRIEVE_TOP_K,
    )
    candidate_names = [h["ten_thu_tuc"] for h in candidate_hits]

    logging.info(
        "[intent_node] retrieved %d candidates for query=%r",
        len(candidate_hits),
        resolved_user_input[:80],
    )

    # ── Bước 2: LLM xác định intent ─────────────────────────────────
    prompt = supervisor_prompt["INTENT_PROMPT_V2"].format(
        query=resolved_user_input,
        raw_query=raw_user_input,
        last_domain=state.get("last_domain") or "null",
        last_procedures=(
            ", ".join(state.get("procedure_names", []))
            if state.get("procedure_names") else "[]"
        ),
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
    confidence: float = float(data.get("confidence", 0.0))

    # Fallback khi confidence thấp nhưng đang trong luồng followup
    if confidence < CONFIDENCE_THRESHOLD:
        if state.get("is_followup") and state.get("last_domain"):
            intent = "legal"
            confidence = max(confidence, 0.75)
        else:
            intent = "unclear"

    logging.info(
        "[intent_node] intent=%s confidence=%.2f | raw_query=%r | resolved=%r",
        intent, confidence, raw_user_input[:60], resolved_user_input[:60],
    )

    await emit(StreamEvent(
        type="progress",
        node="supervisor",
        message="Đang tìm kiếm thủ tục liên quan...",
    ))

    # ── Bước 3: Route ────────────────────────────────────────────────
    if intent in ("chitchat", "unclear"):
        return Command(
            goto="qa",
            update={
                "intent": intent,
                "domain": None,
                "intent_confidence": confidence,
                # Cache candidates phòng qa_node cần tham khảo
                "_qdrant_candidates": candidate_names,
            },
        )

    return Command(
        goto="supervisor",
        update={
            "intent": intent,
            "domain": None,
            "intent_confidence": confidence,
            # Candidates được truyền sang supervisor_node, tránh retrieve 2 lần
            "_qdrant_candidates": candidate_names,
        },
    )

@traceable
async def supervisor_node(state: AgentState) -> Command[Literal["qa", "forms", "location"]]:
    """
    Luồng:
      1. Lấy danh sách ứng viên từ cache `_qdrant_candidates` (do intent_node retrieve).
         Nếu cache rỗng thì retrieve lại từ Qdrant.
      2. LLM chọn thủ tục chính xác từ danh sách ứng viên đó.
      3. Map tên thủ tục → mã thủ tục (name_id.json).
      4. Route sang agent phù hợp (qa / forms / location).
    """
    messages = state["messages"]
    raw_user_input = state["user_input"]
    resolved_user_input = state.get("resolved_user_input") or raw_user_input
    summary = state.get("conversation_summary", "")

    await emit(StreamEvent(
        type="progress",
        node="supervisor",
        message="Đang xác định thủ tục của bạn...",
    ))

    # ── Bước 1: Lấy ứng viên (từ cache hoặc retrieve lại) ───────────
    candidate_names: list[str] = state.get("_qdrant_candidates", [])
    if not candidate_names:
        logging.info(
            "[supervisor_node] Cache trống, re-retrieve từ Qdrant cho query=%r",
            resolved_user_input[:60],
        )
        candidate_hits = await retrieve_procedures(
            query=resolved_user_input,
            top_k=RETRIEVE_TOP_K,
        )
        candidate_names = [h["ten_thu_tuc"] for h in candidate_hits]

    candidate_list_str = "\n".join(f"- {name}" for name in candidate_names)

    logging.info(
        "[supervisor_node] %d candidates được đưa vào LLM:\n%s",
        len(candidate_names),
        candidate_list_str,
    )

    # ── Bước 2: Ngữ cảnh followup (thêm vào system prompt) ──────────
    extra_context = ""
    if state.get("is_followup"):
        extra_context = (
            f"- last_domain: {state.get('last_domain') or 'null'}\n"
            f"- last_procedures: "
            f"{', '.join(state.get('procedure_names', [])) if state.get('procedure_names') else '[]'}\n"
            f"- followup_reason: {state.get('followup_reason') or 'Không có'}"
        )

    # ── Bước 3: LLM chọn thủ tục từ danh sách ứng viên ─────────────
    prompt = supervisor_prompt["SUPERVISOR_PROMPT_V3"].format(
        query=resolved_user_input,
        procedures=candidate_list_str,          # <-- danh sách từ Qdrant, không phải toàn bộ DB
        last_domain=state.get("last_domain") or "null",
        last_procedures=(
            ", ".join(state.get("procedure_names", []))
            if state.get("procedure_names") else "[]"
        ),
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

    logging.info("[supervisor_node] LLM response=%s", response)

    # ── Bước 4: Map tên → mã thủ tục ────────────────────────────────
    name_ids: dict = read_json("app/agents/supervisor", "name_id.json")

    procedures: list[str] = data.get("procedures", []) or []
    fields: list[str] = data.get("fields", []) or []
    pipeline: list[str] = _normalize_pipeline(data.get("pipeline", ["qa"]))

    # Fallback: kế thừa thủ tục trước nếu đây là followup và LLM không chọn được
    if not procedures and state.get("is_followup") and state.get("procedure_names"):
        procedures = state.get("procedure_names", [])
        logging.info(
            "[supervisor_node] Inherited procedures from previous turn: %s", procedures
        )

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
            data={"procedures": []},
        ))

    first_agent = _resolve_first_agent(pipeline, procedure_ids)

    return Command(
        goto=first_agent,
        update={
            "procedures": procedure_ids,
            "procedure_names": procedures,
            "pipeline": pipeline,
            "fields": fields,
            "_qdrant_candidates": [],   # xoá cache sau khi dùng xong
        },
    )
=======
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
    user_input = state["user_input"]

    await emit(StreamEvent(
        type="progress", node="supervisor",
        message="Đang xác định thủ tục của bạn..."
    ))

    prompt = supervisor_prompt["SUPERVISOR_PROMPT_V2"].format(
        query = user_input
    )

    response = await get_response_llm(prompt, messages)
    data = json.loads(response)

    procedures = data.get("procedures", [])

    await emit(StreamEvent(
        type="result", 
        node="supervisor",
        message=f"Đã tìm thấy: {procedures}\n Các bước tiếp theo: {data.get('pipeline', ['qa'])}",
        data={"procedures": procedures}
    ))

    name_ids = read_json("app/agents/supervisor", "name_id.json")

    procedure_ids = [name_ids[proc] for proc in procedures if proc in name_ids]    

    return Command(
        goto=data["pipeline"][0],
        update={
            "procedures": procedure_ids,
            # "messages": [AIMessage(content=json.dumps(data, ensure_ascii=False))],
            "pipeline": data.get("pipeline", ["qa"]),
            "fields": data.get("fields", [])
        },
    )


    

>>>>>>> 3651248e192715c39a28ff6372f5a139d3fcdae0
