import json
import re
import unicodedata
import uuid
from typing import Any, Literal

from langchain_core.messages import AIMessage
from langgraph.graph import END
from langgraph.types import Command, interrupt
from langsmith import traceable

from app.agents.base.state import AgentState, StreamEvent
from app.agents.base.utils import emit
from app.agents.forms.forms_tools import (
    extract_form_fields,
    fill_form_fields,
    get_google_docs_link,
    load_pdf_from_url,
    select_form_url,
)
from app.agents.forms.helper import (
    _build_dynamic_form_payload, 
    _loads_json, 
    _normalize_fields, 
    _build_mode_choice_payload, 
    _detect_mode_from_text
)
from app.db.session import get_db
from app.services.user_service import UserService
from app.agents.qa.qa_tools import fetch_form_pdf_urls


# ──────────────────────────────────────────────────────────
# NODE 1: forms_node – chọn mẫu & emit lựa chọn hướng điền
# ──────────────────────────────────────────────────────────

@traceable
async def forms_node(
    state: AgentState,
) -> Command[Literal["forms_ask_mode", "__end__"]]:
    raw_user_input = state.get("user_input", "")
    resolved_user_input = state.get("resolved_user_input") or raw_user_input
    pdf_urls = state.get("pdf_urls", []) or []
    procedure_ids = state.get("procedures", []) or []

    if not pdf_urls and procedure_ids:
        await emit(
            StreamEvent(
                type="progress",
                node="forms",
                message="Đang nạp trực tiếp danh sách biểu mẫu từ thủ tục đã xác định...",
            )
        )
        try:
            pdf_urls = fetch_form_pdf_urls(procedure_ids)
        except Exception as exc:
            await emit(
                StreamEvent(
                    type="error",
                    node="forms",
                    message=f"Không thể nạp biểu mẫu trực tiếp: {exc}",
                )
            )

    await emit(
        StreamEvent(
            type="progress",
            node="forms",
            message="Đang xác định biểu mẫu cần điền...",
        )
    )

    # ── Bước 1: Chọn mẫu đơn phù hợp ──
    selected_raw = await select_form_url.ainvoke(
        {
            "pdf_urls": pdf_urls,
            "user_input": resolved_user_input,
        }
    )
    selected_payload = _loads_json(selected_raw)
    selected_status = selected_payload.get("status")

    if selected_status == "not_found":
        answer = selected_payload.get("message") or "Tôi chưa tìm thấy biểu mẫu phù hợp để điền."
        await emit(StreamEvent(type="result", node="forms", message=answer))
        return Command(
            goto=END,
            update={"final_response": answer, "messages": [AIMessage(content=answer)]},
        )

    if selected_status == "ambiguous":
        candidates = selected_payload.get("candidates") or []
        lines = [
            selected_payload.get("question") or "Có nhiều biểu mẫu phù hợp, vui lòng chọn rõ mẫu cần điền:"
        ]
        for item in candidates[:5]:
            name = item.get("form_name") or item.get("filename_decoded") or "Biểu mẫu"
            url = item.get("url")
            lines.append(f"- {name}: {url}" if url else f"- {name}")
        answer = "\n".join(lines)
        await emit(StreamEvent(type="result", node="forms", message=answer))
        return Command(
            goto=END,
            update={"final_response": answer, "messages": [AIMessage(content=answer)]},
        )

    if selected_status == "error" or not selected_payload.get("selected_url"):
        answer = f"Có lỗi khi xác định biểu mẫu: {selected_payload.get('error', 'không rõ nguyên nhân')}"
        await emit(StreamEvent(type="error", node="forms", message=answer))
        return Command(
            goto=END,
            update={"final_response": answer, "messages": [AIMessage(content=answer)]},
        )

    pdf_url = selected_payload["selected_url"]
    form_name = selected_payload.get("form_name") or "biểu mẫu"

    # ── Bước 2: Hỏi người dùng chọn hướng điền ──
    mode_choice_payload = _build_mode_choice_payload(form_name, pdf_url)

    await emit(
        StreamEvent(
            type="progress",
            node="forms",
            message=mode_choice_payload["description"],
            data=mode_choice_payload,
        )
    )

    return Command(
        goto="forms_ask_mode",
        update={
            "pdf_urls": pdf_urls,
            "pdf_url_selected": pdf_url,
            "form_name_selected": form_name,
            "forms_mode_choice_payload": mode_choice_payload,
        },
    )


# ──────────────────────────────────────────────────────────
# NODE 2: forms_ask_mode_node – interrupt chờ lựa chọn hướng
# ──────────────────────────────────────────────────────────

@traceable
async def forms_ask_mode_node(
    state: AgentState,
) -> Command[Literal["forms_route"]]:
    mode_choice_payload = state.get("forms_mode_choice_payload")
    # interrupt trả nguyên payload lên frontend, chờ người dùng submit {"mode": "google_docs"|"dynamic_form"}
    submitted = interrupt(mode_choice_payload) or {}

    if not isinstance(submitted, dict):
        submitted = {"mode": str(submitted).strip()}

    # Hỗ trợ cả hai format: {"mode": "..."} và {"value": "..."}
    mode = submitted.get("mode") or submitted.get("value") or ""

    # Nếu người dùng nhập text tự do (vd "tôi muốn Google Docs")
    if mode not in ("google_docs", "dynamic_form"):
        detected = _detect_mode_from_text(mode)
        mode = detected or "dynamic_form"  # default: form tự động

    return Command(
        goto="forms_route",
        update={
            "forms_fill_mode": mode,
            "forms_mode_choice_payload": None,
        },
    )


# ──────────────────────────────────────────────────────────
# NODE 3: forms_route_node – định tuyến theo lựa chọn
# ──────────────────────────────────────────────────────────

@traceable
async def forms_route_node(
    state: AgentState,
) -> Command[Literal["forms_google_docs", "forms_extract", "__end__"]]:
    mode = state.get("forms_fill_mode", "dynamic_form")

    await emit(
        StreamEvent(
            type="progress",
            node="forms",
            message=(
                "Đang tạo Google Docs link..." if mode == "google_docs"
                else "Đang chuẩn bị trích xuất trường thông tin từ biểu mẫu..."
            ),
        )
    )

    if mode == "google_docs":
        return Command(goto="forms_google_docs")
    return Command(goto="forms_extract")


# ──────────────────────────────────────────────────────────
# NODE 4a: forms_google_docs_node – convert PDF → Google Docs
# ──────────────────────────────────────────────────────────

@traceable
async def forms_google_docs_node(state: AgentState) -> dict:
    pdf_url = state.get("pdf_url_selected") or ""
    form_name = state.get("form_name_selected") or "Biểu mẫu"

    if not pdf_url:
        answer = "Không tìm thấy URL biểu mẫu để tạo Google Docs."
        await emit(StreamEvent(type="error", node="forms", message=answer))
        return {
            "final_response": answer,
            "messages": [AIMessage(content=answer)],
        }

    gdocs_raw = await get_google_docs_link.ainvoke(
        {
            "s3_url": pdf_url,
            "file_name": form_name,
        }
    )
    gdocs_payload = _loads_json(gdocs_raw)

    if not gdocs_payload.get("success"):
        error_msg = gdocs_payload.get("error", "không rõ nguyên nhân")
        answer = (
            f"Không thể tạo Google Docs link: {error_msg}\n\n"
            f"Bạn vẫn có thể tải trực tiếp PDF gốc: [{form_name}]({pdf_url})"
        )
        await emit(StreamEvent(type="error", node="forms", message=answer))
        return {
            "final_response": answer,
            "messages": [AIMessage(content=answer)],
        }

    embed_url = gdocs_payload["embed_url"]
    answer = (
        f"Tôi đã tạo xong biểu mẫu **{form_name}**.\n\n"
        f"[Mở và chỉnh sửa trực tiếp tại đây]({embed_url})\n\n"
        "_Bạn có thể chỉnh sửa, điền thông tin và tải xuống dưới dạng Word/PDF._"
    )

    await emit(
        StreamEvent(
            type="result",
            node="forms",
            message=answer,
            data={"google_docs_url": embed_url},
        )
    )

    return {
        "google_docs_url": embed_url,
        "final_response": answer,
        "messages": [AIMessage(content=answer)],
    }


# ──────────────────────────────────────────────────────────
# NODE 4b: forms_extract_node – tải PDF & trích xuất trường
# ──────────────────────────────────────────────────────────

@traceable
async def forms_extract_node(
    state: AgentState,
) -> Command[Literal["forms_wait_input", "__end__"]]:
    pdf_url = state.get("pdf_url_selected") or ""
    form_name = state.get("form_name_selected") or "biểu mẫu"
    user_id = state.get("user_id")

    if not pdf_url:
        answer = "Không tìm thấy URL biểu mẫu để trích xuất trường."
        await emit(StreamEvent(type="error", node="forms", message=answer))
        return Command(
            goto=END,
            update={"final_response": answer, "messages": [AIMessage(content=answer)]},
        )

    # Tải PDF
    await emit(
        StreamEvent(
            type="progress",
            node="forms",
            message=f"Đã chọn {form_name}, đang tải file PDF...",
        )
    )

    load_raw = await load_pdf_from_url.ainvoke({"pdf_url": pdf_url})
    load_payload = _loads_json(load_raw)
    if not load_payload.get("success"):
        answer = f"Không thể tải biểu mẫu PDF: {load_payload.get('error', 'không rõ nguyên nhân')}"
        await emit(StreamEvent(type="error", node="forms", message=answer))
        return Command(
            goto=END,
            update={"final_response": answer, "messages": [AIMessage(content=answer)]},
        )

    pdf_path = load_payload.get("pdf_path")

    # Trích xuất trường
    await emit(
        StreamEvent(
            type="progress",
            node="forms",
            message="Đang trích xuất các trường thông tin từ biểu mẫu...",
        )
    )

    extract_raw = await extract_form_fields.ainvoke({"pdf_path": pdf_path})
    extract_payload = _loads_json(extract_raw)
    if not extract_payload.get("success"):
        answer = f"Không thể trích xuất trường thông tin: {extract_payload.get('error', 'không rõ nguyên nhân')}"
        await emit(StreamEvent(type="error", node="forms", message=answer))
        return Command(
            goto=END,
            update={"final_response": answer, "messages": [AIMessage(content=answer)]},
        )

    fields = _normalize_fields(extract_payload.get("fields", []) or [])
    if not fields:
        answer = "Tôi không tìm thấy trường nào có thể điền tự động trong biểu mẫu này."
        await emit(StreamEvent(type="result", node="forms", message=answer))
        return Command(
            goto=END,
            update={"final_response": answer, "messages": [AIMessage(content=answer)]},
        )
    
    with next(get_db()) as db:
        user_service = UserService(db)
        user_profile = user_service.get_profile_for_chatbot(user_id) or {}

    form_payload = _build_dynamic_form_payload(fields, pdf_path, user_profile)

    await emit(
        StreamEvent(
            type="progress",
            node="forms",
            message="Đã trích xuất xong các trường, đang chờ người dùng nhập form...",
        )
    )

    return Command(
        goto="forms_wait_input",
        update={
            "pdf_local_path": pdf_path,
            "extracted_form_fields": fields,
            "dynamic_form_payload": form_payload,
        },
    )


# ──────────────────────────────────────────────────────────
# NODE 5: forms_wait_input_node – interrupt chờ người dùng nhập form
# ──────────────────────────────────────────────────────────

@traceable
async def forms_wait_input_node(state: AgentState) -> Command[Literal["forms_fill"]]:
    form_payload = state.get("dynamic_form_payload")
    submitted_values = interrupt(form_payload) or {}

    if not isinstance(submitted_values, dict):
        submitted_values = {}

    return Command(
        goto="forms_fill",
        update={
            "submitted_form_values": submitted_values,
            "dynamic_form_payload": None,
        },
    )


# ──────────────────────────────────────────────────────────
# NODE 6: forms_fill_node – điền PDF và xuất kết quả
# ──────────────────────────────────────────────────────────

@traceable
async def forms_fill_node(state: AgentState) -> dict:
    pdf_path = state.get("pdf_local_path")
    fields = state.get("extracted_form_fields", []) or []
    submitted_values = state.get("submitted_form_values") or {}

    field_values = {}
    for field in fields:
        raw_value = submitted_values.get(field["field_id"])
        value = str(raw_value).strip() if raw_value is not None else ""
        if not value:
            continue

        field_values[field["field_id"]] = {
            "value": value,
            "x": field.get("x"),
            "y": field.get("y"),
            "page": field.get("page", 0),
            "label": field.get("label"),
        }

    await emit(
        StreamEvent(
            type="progress",
            node="forms",
            message="Đã nhận dữ liệu từ form, đang điền vào PDF...",
        )
    )

    filled_raw = await fill_form_fields.ainvoke(
        {
            "pdf_path": pdf_path,
            "field_values": field_values,
        }
    )
    filled_payload = _loads_json(filled_raw)

    if not filled_payload.get("success"):
        answer = f"Đã nhận dữ liệu nhưng chưa thể điền biểu mẫu: {filled_payload.get('error', 'không rõ nguyên nhân')}"
        await emit(StreamEvent(type="error", node="forms", message=answer))
        return {
            "final_response": answer,
            "messages": [AIMessage(content=answer)],
            "submitted_form_values": submitted_values,
        }

    filled_pdf_url = filled_payload.get("pdf_url")
    final_response = (
        f"Tôi đã điền xong biểu mẫu cho bạn. [Tải mẫu đã điền tại đây]({filled_pdf_url})"
        if filled_pdf_url
        else "Tôi đã điền xong biểu mẫu, nhưng hiện chưa tạo được liên kết tải file."
    )

    await emit(
        StreamEvent(
            type="result",
            node="forms",
            message=final_response,
            data={"filled_pdf_url": filled_pdf_url},
        )
    )

    return {
        "submitted_form_values": submitted_values,
        "filled_pdf_url": filled_pdf_url,
        "final_response": final_response,
        "messages": [AIMessage(content="Tôi đã nhận dữ liệu từ form động và hoàn tất việc điền biểu mẫu.")],
    }
