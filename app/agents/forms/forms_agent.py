"""
Forms Agent – tác tử điền biểu mẫu hành chính.

Luồng:
  1. forms_node         – chọn mẫu đơn  → hỏi người dùng muốn điền theo hướng nào
  2. forms_ask_mode_node– interrupt để người dùng chọn hướng điền (google_docs | dynamic_form)
  3. forms_route_node   – đọc lựa chọn → rẽ nhánh
       ├─ google_docs   → forms_google_docs_node  (convert → Google Docs link)
       └─ dynamic_form  → forms_extract_node      → forms_wait_input_node → forms_fill_node
"""

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
from app.agents.forms.helper import _build_dynamic_form_payload

TOOLS = [select_form_url, load_pdf_from_url, extract_form_fields, fill_form_fields, get_google_docs_link]

# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────

def _loads_json(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text or "field"


def _normalize_fields(fields: list[dict]) -> list[dict]:
    normalized = []
    seen: dict[str, int] = {}

    for idx, field in enumerate(fields, start=1):
        label = str(field.get("label") or f"Trường {idx}").strip()
        page = int(field.get("page", 0) or 0)
        base_id = _slugify(field.get("field_id") or label)

        seen[base_id] = seen.get(base_id, 0) + 1
        field_id = base_id if seen[base_id] == 1 else f"{base_id}_{seen[base_id]}"

        normalized.append(
            {
                "field_id": field_id,
                "label": label,
                "x": field.get("x"),
                "y": field.get("y"),
                "page": page,
            }
        )

    return normalized


def _build_mode_choice_payload(form_name: str, pdf_url: str) -> dict:
    """Payload để hỏi người dùng chọn hướng điền, tái sử dụng cơ chế dynamic_form sẵn có."""
    description = (
        f"Tôi đã tìm thấy mẫu đơn **{form_name}**. "
        "Bạn muốn điền theo hướng nào?\n\n"
        "- **1** – Chỉnh sửa trực tiếp trên mẫu đơn\n"
        "- **2** – Điền mẫu đơn tự động "
    )

    return {
        "kind": "dynamic_form",
        "request_id": str(uuid.uuid4()),
        "title": f"Chọn cách điền cho {form_name}",
        "description": description,
        "submit_label": "Tiếp tục",
        "pdf_url": pdf_url,
        "fields": [
            {
                "field_id": "mode",
                "label": "Cách điền",
                "type": "select",
                "required": True,
                "placeholder": "Chọn 1 hoặc 2",
                "options": [
                    {"value": "google_docs", "label": "1 – Chỉnh sửa trực tiếp trên Google Docs"},
                    {"value": "dynamic_form", "label": "2 – Điền form tự động (xuất PDF)"},
                ],
            }
        ],
    }


def _detect_mode_from_text(text: str) -> str | None:
    """Cố gắng nhận diện lựa chọn từ text tự do của người dùng."""
    t = (text or "").strip().lower()
    # Rõ ràng chọn 1 / google docs
    if t in ("1", "1.", "1 ", "option 1") or "google" in t or "docs" in t or "link" in t:
        return "google_docs"
    # Rõ ràng chọn 2 / form tự động
    if t in ("2", "2.", "2 ", "option 2") or "tự động" in t or "dynamic" in t or "pdf" in t or "điền tự" in t:
        return "dynamic_form"
    return None


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

    form_payload = _build_dynamic_form_payload(fields, pdf_path)

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
