import asyncio
import json
import random
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
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
from app.helpers.utils.exception import CustomException
from app.helpers.utils.logger import logging

MAX_QA_AGENT_ITER = 5
QA_ACCEPT_CONFIDENCE = 0.8


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _merge_pdf_urls(existing: list[dict] | None, incoming: list[dict] | None) -> list[dict]:
    current = existing or []
    new_items = incoming or []
    existing_keys = {item.get("loai_giay_to") for item in current}
    return current + [item for item in new_items if item.get("loai_giay_to") not in existing_keys]


def _build_qa_agent_system_prompt() -> str:
    return """Bạn là QA agent cho trợ lý thủ tục hành chính Việt Nam.

Mục tiêu:
- Trả lời đúng trọng tâm câu hỏi người dùng.
- Chỉ dùng dữ liệu lấy từ tool hoặc ngữ cảnh đã có.
- Tự kiểm tra chất lượng câu trả lời, rồi tiếp tục quan sát → suy luận → hành động cho đến khi câu trả lời đạt yêu cầu hoặc không thể cải thiện thêm trong giới hạn vòng lặp.

Bạn có thể tự quyết định:
- Có cần gọi tool để lấy thêm dữ liệu hay không.
- Nên gọi tool nào và với tham số nào.
- Khi nào nên dừng.

Tiêu chí một câu trả lời đạt yêu cầu:
1. Grounded: mọi thông tin thực tế đều bám dữ liệu.
2. Complete: trả lời đủ ý chính theo câu hỏi người dùng.
3. Clear: dễ đọc, có cấu trúc, tiếng Việt tự nhiên.
4. Link format OK: nếu có link thì phải ở Markdown, không lộ URL thô trong thân bài.
5. Honest: nếu thiếu dữ liệu thì nói rõ thiếu gì, không đoán.

Quy tắc trả lời:
- Nếu có nhiều thủ tục, trình bày tách riêng từng thủ tục.
- Nếu có link từ dữ liệu, giữ nguyên link gốc và trình bày Markdown.
- Nếu pipeline có "forms", chỉ trả lời thông tin có sẵn, không tự chuyển sang hướng dẫn điền biểu mẫu.
- Không bịa thông tin ngoài dữ liệu đã quan sát.
- Khi chưa đủ dữ liệu, ưu tiên gọi tool thay vì suy diễn.

Khi KHÔNG gọi tool, bắt buộc chỉ trả về JSON hợp lệ theo schema:
{
  "status": "continue" | "done",
  "answer": "câu trả lời tiếng Việt cho người dùng",
  "confidence": 0.0,
  "self_review": {
    "grounded": true,
    "complete": true,
    "clear": true,
    "link_format_ok": true,
    "needs_more_data": false,
    "issues": ["..."]
  },
  "next_action": "finalize" | "revise" | "call_tool",
  "reasoning_summary": "mô tả ngắn gọn lý do cho bước tiếp theo"
}

Diễn giải:
- status=continue khi câu trả lời chưa đạt hoặc bạn vẫn muốn gọi tool / sửa tiếp.
- status=done chỉ khi câu trả lời đã đạt yêu cầu hoặc không thể lấy thêm dữ liệu hữu ích nữa.
- Nếu needs_more_data=true thì thường nên gọi tool ở vòng tiếp theo.
- reasoning_summary phải ngắn gọn, không lan man.

QUAN TRỌNG: Nếu đã tốt, "next_action" : "finalize", ĐỂ NGUYÊN draft_answer không chỉnh sửa gì thêm, đặc biệt giữ nguyên link gốc
"""


def _build_qa_agent_user_prompt(
    *,
    user_input: str,
    pipeline: list[str],
    procedure_names: list[str],
    procedure_ids: list[str],
    default_fields: list[str],
    initial_context: dict,
    draft_answer: str,
) -> str:
    return f"""Câu hỏi người dùng:
{user_input}

Pipeline hiện tại:
{_json_dumps(pipeline)}

Thủ tục đã match:
- Tên thủ tục: {_json_dumps(procedure_names)}
- Mã thủ tục: {_json_dumps(procedure_ids)}

Fields mặc định supervisor đã chọn:
{_json_dumps(default_fields)}

Quan sát ban đầu từ cơ sở dữ liệu (raw JSON, ưu tiên dùng trực tiếp):
{_json_dumps(initial_context)}

Bản nháp câu trả lời hiện tại:
{draft_answer}

Hãy tự đánh giá bản nháp này.
- Nếu đã tốt, có thể finalize, ĐỂ NGUYÊN draft_answer không chỉnh sửa gì thêm.
- Nếu chưa đủ dữ liệu hoặc cần kiểm chứng, hãy tự quyết định gọi tool phù hợp.
"""


def _build_continue_prompt(review_payload: dict) -> str:
    issues = review_payload.get("self_review", {}).get("issues") or []
    reasoning = review_payload.get("reasoning_summary") or ""
    next_action = review_payload.get("next_action") or "revise"
    return (
        "Câu trả lời trước chưa đạt ngưỡng chấp nhận. "
        f"Issues hiện tại: {_json_dumps(issues)}. "
        f"Next action gợi ý từ bạn: {next_action}. "
        f"Lý do: {reasoning}. "
        "Hãy tiếp tục vòng lặp: quan sát dữ liệu đã có, quyết định có cần gọi tool hay không, rồi trả về JSON mới hoặc tool call mới."
    )


def _answer_meets_bar(payload: dict) -> bool:
    answer = str(payload.get("answer") or "").strip()
    if not answer:
        return False

    review = payload.get("self_review") or {}
    confidence = float(payload.get("confidence") or 0.0)
    status = payload.get("status")

    return bool(
        status == "done"
        and confidence >= QA_ACCEPT_CONFIDENCE
        and review.get("grounded") is True
        and review.get("complete") is True
        and review.get("clear") is True
        and review.get("link_format_ok") is True
        and review.get("needs_more_data") is not True
    )


async def _invoke_qa_agent(messages: list, tools: list) -> AIMessage:
    llm_with_tools = _llm.bind_tools(tools)
    return await asyncio.to_thread(
        llm_with_tools.invoke,
        [SystemMessage(content=_build_qa_agent_system_prompt()), *messages],
    )


@traceable
async def qa_node(state: AgentState) -> Command[Literal["forms", "location", "__end__"]]:
    intent = state.get("intent", "chitchat")

    if intent in ("chitchat", "unclear"):
        await emit(StreamEvent(type="progress", node="qa", message="Đang xử lý câu hỏi..."))
        await emit(StreamEvent(type="result", node="qa", message=_default_reply(intent)))
        return Command(
            goto=END,
            update={"final_response": _default_reply(intent)},
        )

    current_agent = "qa"
    pipeline = state["pipeline"]
    next_agent = get_next_agent(pipeline, current_agent)
    messages = state["messages"]
    user_input = state.get("resolved_user_input") or state["user_input"]
    procedure_ids = state["procedures"]
    procedure_names = state.get("procedure_names", [])
    default_fields = state.get("fields", [])

    logging.info("[qa_node] user_input=%s procedures=%s", user_input, procedure_ids)

    await emit(StreamEvent(type="progress", node="qa", message="Đang tìm thông tin cho thủ tục..."))

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

    try:
        initial_case = SupervisorOutput(procedures=procedure_ids, fields=default_fields)
        initial_plan = build_query_plan(initial_case)
        initial_payload = execute_query_plan(initial_plan, initial_case.procedures)
        logging.info(
            "[qa_node] Initial query executed. main_rows=%s child_tables=%s",
            initial_payload["main"]["row_count"],
            list((initial_payload.get("children") or {}).keys()),
        )
    except CustomException as exc:
        logging.error("[qa_node] Failed to build SQL: %s", exc)
        raise
    except Exception as exc:
        logging.error("[qa_node] DB execution error: %s", exc, exc_info=True)
        raise

    merged_pdf_urls = _merge_pdf_urls(state.get("pdf_urls"), initial_payload.get("pdf_urls"))

    await emit(StreamEvent(type="progress", node="qa", message="Đang tổng hợp câu trả lời..."))

    draft_answer = await get_response_llm(
        prompt=supervisor_prompt["ANSWER_GENERATION"].format(
            query=user_input,
            context=_json_dumps(initial_payload),
            pipeline=pipeline,
        ),
        messages=messages,
        summary=state.get("conversation_summary", ""),
        max_messages=6,
    )

    @tool
    async def list_queryable_fields() -> dict:
        """Trả về danh sách bảng/cột hợp lệ để agent chọn fields cho lần truy vấn tiếp theo."""
        return {
            "tables": TABLE_COLUMNS,
            "examples": [
                "thu_tuc.ten_thu_tuc",
                "thu_tuc.co_quan_thuc_hien",
                "thanh_phan_ho_so.loai_giay_to",
                "thanh_phan_ho_so.mau_don_to_khai",
                "cach_thuc_thuc_hien.thoi_han_giai_quyet",
                "cach_thuc_thuc_hien.phi_le_phi",
                "can_cu_phap_ly.trich_yeu",
            ],
        }

    @tool
    async def query_procedure_context(
        fields: list[str] | None = None,
        procedures: list[str] | None = None,
    ) -> dict:
        """Query raw dữ liệu thủ tục từ DB. fields dùng dạng 'bang.cot'. Nếu bỏ trống sẽ dùng fields mặc định từ supervisor. Nếu bỏ procedures sẽ dùng procedures đã match."""
        selected_fields = fields or default_fields
        selected_procedures = procedures or procedure_ids
        case = SupervisorOutput(procedures=selected_procedures, fields=selected_fields)
        plan = build_query_plan(case)
        payload = execute_query_plan(plan, case.procedures)
        payload["requested_fields"] = selected_fields
        payload["requested_procedures"] = selected_procedures
        return payload

    tools = [list_queryable_fields, query_procedure_context]
    tool_registry = {tool_obj.name: tool_obj for tool_obj in tools}

    agent_messages: list = [
        HumanMessage(
            content=_build_qa_agent_user_prompt(
                user_input=user_input,
                pipeline=pipeline,
                procedure_names=procedure_names,
                procedure_ids=procedure_ids,
                default_fields=default_fields,
                initial_context=initial_payload,
                draft_answer=draft_answer,
            )
        )
    ]

    latest_answer = draft_answer

    for iteration in range(MAX_QA_AGENT_ITER):
        await emit(
            StreamEvent(
                type="progress",
                node="qa",
                message=f"QA agent đang tự kiểm tra chất lượng câu trả lời ({iteration + 1}/{MAX_QA_AGENT_ITER})...",
            )
        )

        response = await _invoke_qa_agent(agent_messages, tools)
        agent_messages.append(response)
        tool_calls = response.tool_calls or []

        if tool_calls:
            logging.info("[qa_node] Agent requested tools: %s", [tc["name"] for tc in tool_calls])
            tool_messages: list[ToolMessage] = []

            for tool_call in tool_calls:
                tool_name = tool_call["name"]
                tool_fn = tool_registry.get(tool_name)
                if not tool_fn:
                    payload = {"error": f"Unknown tool: {tool_name}"}
                else:
                    try:
                        payload = await tool_fn.ainvoke(tool_call.get("args") or {})
                    except Exception as exc:
                        logging.error("[qa_node] Tool '%s' failed: %s", tool_name, exc, exc_info=True)
                        payload = {"error": str(exc)}

                if tool_name == "query_procedure_context" and isinstance(payload, dict):
                    merged_pdf_urls = _merge_pdf_urls(merged_pdf_urls, payload.get("pdf_urls"))

                tool_messages.append(
                    ToolMessage(
                        content=_json_dumps(payload),
                        tool_call_id=tool_call["id"],
                    )
                )

            agent_messages.extend(tool_messages)
            continue

        review_payload = safe_json_loads(response.content, fallback={})
        if not review_payload:
            logging.warning("[qa_node] Agent returned non-JSON final content, asking to retry formatting.")
            agent_messages.append(
                HumanMessage(
                    content="Bạn vừa trả về sai định dạng. Hãy tiếp tục vòng lặp và chỉ trả về JSON hợp lệ theo đúng schema đã yêu cầu."
                )
            )
            continue

        candidate_answer = str(review_payload.get("answer") or "").strip()
        next_action = review_payload.get("next_action", "")

        # candidate_answer = str(review_payload.get("answer") or "").strip()
        # if candidate_answer:
        #     latest_answer = candidate_answer

        if candidate_answer and next_action != "finalize":
            latest_answer = candidate_answer

        logging.info("[qa_node] Review payload at iter %s: %s", iteration + 1, review_payload)

        if _answer_meets_bar(review_payload):
            logging.info("[qa_node] Answer accepted at iteration %s", iteration + 1)
            break

        if iteration == MAX_QA_AGENT_ITER - 1:
            logging.warning("[qa_node] Reached max QA iterations, using best available answer.")
            break

        agent_messages.append(HumanMessage(content=_build_continue_prompt(review_payload)))

    final_answer = latest_answer or draft_answer

    logging.info("[qa_node] Next agent: %s", next_agent)
    await emit(
        StreamEvent(
            type="result",
            node="qa",
            message=final_answer,
            data={"answer": final_answer},
        )
    )

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
