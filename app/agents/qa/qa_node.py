import asyncio
import json
import random
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END
from langgraph.types import Command
from langsmith import traceable

from app.agents.base.state import AgentState, StreamEvent, SupervisorOutput
from app.agents.base.utils import _default_reply, emit, get_next_agent
from app.agents.qa.qa_tools import (
    TABLE_COLUMNS,
    build_query_plan,
    execute_query_plan,
)
from app.agents.supervisor.constants import NO_PROCEDURE_ANSWERS
from app.core.config import supervisor_prompt
from app.helpers.utils.common import _llm, get_response_llm, safe_json_loads
from app.helpers.utils.logger import logging

# ❌ ĐÃ BỎ: MAX_QA_AGENT_ITER, QA_ACCEPT_CONFIDENCE, _json_dumps riêng

QA_DEFAULT_FIELDS = [
    "thu_tuc.ten_thu_tuc",
    "thu_tuc.linh_vuc",
    "thu_tuc.trinh_tu_thuc_hien",
    "thu_tuc.doi_tuong_thuc_hien",
    "thu_tuc.co_quan_thuc_hien",
    "thu_tuc.co_quan_co_tham_quyen",
    "thu_tuc.dia_chi_tiep_nhan_hs",
    "thu_tuc.yeu_cau_dieu_kien",
    "thu_tuc.ket_qua_thuc_hien",
    "thu_tuc.keT_qua_thuc_hien".replace("keT", "ket"),  # fallback nếu typo
    "thu_tuc.tu_khoa",
    "thu_tuc.mo_ta",
]


def _compact_payload(payload: dict, max_rows_per_table: int = 6) -> str:
    """
    Rút gọn payload DB về dạng ngắn gọn để đưa vào prompt LLM.
    Giảm ~70% token so với json.dumps toàn bộ rows.
    """
    def short_row(r: dict) -> dict:
        return {k: (v if isinstance(v, (int, float)) or not v else str(v)[:300])
                for k, v in r.items() if v not in (None, "", [], {})}

    main_rows = payload.get("main", {}).get("rows", []) or []
    children = payload.get("children", {}) or {}
    out = {
        "procedures": [
            {k: short_row(r).get(k) for k in ("ma_thu_tuc", "ten_thu_tuc", "trinh_tu_thuc_hien",
                                                "co_quan_thuc_hien", "dia_chi_tiep_nhan_hs",
                                                "yeu_cau_dieu_kien", "ket_qua_thuc_hien")}
            for r in main_rows[:max_rows_per_table]
        ],
        "forms": [short_row(r) for r in (children.get("thanh_phan_ho_so", {}).get("rows", []) or [])[:max_rows_per_table]],
        "process": [short_row(r) for r in (children.get("cach_thuc_thuc_hien", {}).get("rows", []) or [])[:max_rows_per_table]],
        "legal_basis": [short_row(r) for r in (children.get("can_cu_phap_ly", {}).get("rows", []) or [])[:3]],
    }
    return json.dumps(out, ensure_ascii=False)


def _build_qa_one_pass_prompt(user_input: str, procedure_names: list[str],
                                procedure_ids: list[str], context: str,
                                pipeline: list[str]) -> str:
    return f"""Bạn là trợ lý thủ tục hành chính Việt Nam. Nhiệm vụ: trả lời DUY NHẤT 1 LẦN (không self-eval).

Câu hỏi: {user_input}

Thủ tục đã match: {json.dumps(procedure_names, ensure_ascii=False)}
Mã thủ tục: {json.dumps(procedure_ids)}

Dữ liệu từ cơ sở dữ liệu (đã được rút gọn):
{context}

Pipeline phía sau: {json.dumps(pipeline)}

QUY TẮC BẮT BUỘC (áp dụng trong 1 câu trả lời duy nhất):
1. Grounded: chỉ dùng thông tin có trong dữ liệu trên. Tuyệt đối không bịa.
2. Đủ ý chính theo câu hỏi, tiếng Việt tự nhiên, có cấu trúc Markdown.
3. Nếu dữ liệu thiếu, nói rõ phần thiếu.
4. Nếu có link S3 từ cột mau_don_to_khai, giữ nguyên link Markdown.
5. Nếu pipeline có "forms", KHÔNG hướng dẫn điền biểu mẫu, chỉ trả lời thông tin.
6. Kết thúc bằng phần "Độ tin cậy: XX%" (ước lượng 0-100).

Trả lời:"""


async def _run_initial_query_async(procedure_ids: list[str], default_fields: list[str]) -> dict:
    """Chạy SQL build + execute trong thread pool, không block event loop."""
    case = SupervisorOutput(procedures=procedure_ids, fields=default_fields)

    def _sync():
        plan = build_query_plan(case)
        return execute_query_plan(plan, case.procedures)

    return await asyncio.to_thread(_sync)


@traceable
async def qa_node(state: AgentState) -> Command[Literal["forms", "location", "__end__"]]:
    intent = state.get("intent", "chitchat")
    user_input = state.get("resolved_user_input") or state["user_input"]
    procedure_ids = state.get("procedures", []) or []
    procedure_names = state.get("procedure_names", []) or []
    pipeline = state.get("pipeline", []) or []
    next_agent = get_next_agent(pipeline, "qa")

    # ── Short-circuit chitchat/unclear ───────────────────────────────────
    if intent in ("chitchat", "unclear"):
        reply = _default_reply(intent)
        await emit(StreamEvent(type="result", node="qa", message=reply))
        return Command(
            goto=END,
            update={"final_response": reply, "messages": [AIMessage(content=reply)]},
        )

    # ── Short-circuit không match procedure ──────────────────────────────
    if not procedure_ids:
        answer = random.choice(NO_PROCEDURE_ANSWERS)
        await emit(StreamEvent(type="result", node="qa", message=answer))
        return Command(
            goto=next_agent,
            update={
                "final_response": answer,
                "messages": [AIMessage(content=answer)],
                "last_answer": answer,
                "last_domain": state.get("domain"),
                "last_procedures": procedure_ids,
            },
        )

    await emit(StreamEvent(type="progress", node="qa", message="Đang truy vấn dữ liệu thủ tục..."))

    fields = state.get("fields") or QA_DEFAULT_FIELDS
    try:
        initial_payload = await _run_initial_query_async(procedure_ids, fields)
    except Exception as exc:
        logging.error("[qa_node] DB error: %s", exc, exc_info=True)
        answer = f"Hiện không thể truy vấn dữ liệu thủ tục. Bạn thử lại sau ít phút nhé."
        return Command(
            goto=END,
            update={"final_response": answer, "messages": [AIMessage(content=answer)]},
        )

    merged_pdf_urls = (state.get("pdf_urls") or []) + (initial_payload.get("pdf_urls") or [])
    seen = set()
    dedup = []
    for item in merged_pdf_urls:
        key = item.get("loai_giay_to")
        if key and key not in seen:
            seen.add(key)
            dedup.append(item)
    merged_pdf_urls = dedup

    compact_ctx = _compact_payload(initial_payload)

    await emit(StreamEvent(type="progress", node="qa", message="Đang tạo câu trả lời..."))

    prompt = _build_qa_one_pass_prompt(
        user_input=user_input,
        procedure_names=procedure_names,
        procedure_ids=procedure_ids,
        context=compact_ctx,
        pipeline=pipeline,
    )

    # ❌ ĐÃ BỎ VÒNG SELF-EVAL. Chỉ 1 LLM call duy nhất.
    final_answer = await get_response_llm(
        prompt=prompt,
        messages=state.get("messages", []),
        summary=state.get("conversation_summary", ""),
        max_messages=4,  # giảm từ 6
    )

    await emit(StreamEvent(type="result", node="qa", message=final_answer))

    return Command(
        goto=next_agent,
        update={
            "final_response": final_answer,
            "messages": [AIMessage(content=final_answer)],
            "pdf_urls": merged_pdf_urls,
            "last_answer": final_answer,
            "last_domain": state.get("domain"),
            "last_procedures": procedure_ids,
        },
    )
