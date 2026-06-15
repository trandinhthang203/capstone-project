import json
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.types import interrupt
from langsmith import traceable

from app.agents.base.state import AgentState, StreamEvent
from app.agents.base.utils import emit
from app.agents.forms.forms_tools import (
    extract_form_fields,
    fill_form_fields,
    load_pdf_from_url,
    select_form_url,
)
from app.agents.forms.helper import _build_dynamic_form_payload

TOOLS = [select_form_url, load_pdf_from_url, extract_form_fields, fill_form_fields]


def _loads_json(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


@traceable
async def forms_node(state: AgentState) -> dict:
    user_input = state.get("user_input", "")
    pdf_urls = state.get("pdf_urls", []) or []

    await emit(
        StreamEvent(
            type="progress",
            node="forms",
            message="Đang xác định biểu mẫu cần điền...",
        )
    )

    selected_raw = await select_form_url.ainvoke(
        {
            "pdf_urls": pdf_urls,
            "user_input": user_input,
        }
    )
    selected_payload = _loads_json(selected_raw)
    selected_status = selected_payload.get("status")

    if selected_status == "not_found":
        answer = selected_payload.get("message") or "Tôi chưa tìm thấy biểu mẫu phù hợp để điền."
        await emit(StreamEvent(type="result", node="forms", message=answer))
        return {"final_response": answer, "messages": [AIMessage(content=answer)]}

    if selected_status == "ambiguous":
        candidates = selected_payload.get("candidates") or []
        lines = [selected_payload.get("question") or "Có nhiều biểu mẫu phù hợp, vui lòng chọn rõ mẫu cần điền:"]
        for item in candidates[:5]:
            name = item.get("form_name") or item.get("filename_decoded") or item.get("url") or "Biểu mẫu"
            url = item.get("url")
            lines.append(f"- {name}: {url}" if url else f"- {name}")
        answer = "\n".join(lines)
        await emit(StreamEvent(type="result", node="forms", message=answer))
        return {"final_response": answer, "messages": [AIMessage(content=answer)]}

    if selected_status == "error" or not selected_payload.get("selected_url"):
        answer = f"Có lỗi khi xác định biểu mẫu: {selected_payload.get('error', 'không rõ nguyên nhân')}"
        await emit(StreamEvent(type="error", node="forms", message=answer))
        return {"final_response": answer, "messages": [AIMessage(content=answer)]}

    pdf_url = selected_payload["selected_url"]
    form_name = selected_payload.get("form_name") or "biểu mẫu"

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
        return {"final_response": answer, "messages": [AIMessage(content=answer)]}

    pdf_path = load_payload.get("pdf_path")

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
        answer = f"Không thể trích xuất trường thông tin từ biểu mẫu: {extract_payload.get('error', 'không rõ nguyên nhân')}"
        await emit(StreamEvent(type="error", node="forms", message=answer))
        return {"final_response": answer, "messages": [AIMessage(content=answer)]}

    fields = extract_payload.get("fields", []) or []
    if not fields:
        answer = "Tôi không tìm thấy trường nào có thể điền tự động trong biểu mẫu này."
        await emit(StreamEvent(type="result", node="forms", message=answer))
        return {"final_response": answer, "messages": [AIMessage(content=answer)]}

    form_payload = _build_dynamic_form_payload(fields, pdf_path)

    await emit(
        StreamEvent(
            type="progress",
            node="forms",
            message="Đã trích xuất xong các trường, đang chờ người dùng nhập form...",
        )
    )

    submitted_values = interrupt(form_payload) or {}
    if not isinstance(submitted_values, dict):
        submitted_values = {}

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
            "submitted_form_values": submitted_values,
            "dynamic_form_payload": None,
            "final_response": answer,
            "messages": [AIMessage(content=answer)],
        }

    filled_pdf_url = filled_payload.get("pdf_url")
    final_response = (
        f"Tôi đã điền xong biểu mẫu cho bạn. [Mẫu tại đây]({filled_pdf_url})"
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
        "dynamic_form_payload": None,
        "final_response": final_response,
        "messages": [AIMessage(content="Tôi đã nhận dữ liệu từ form động và hoàn tất việc điền biểu mẫu.")],
    }
