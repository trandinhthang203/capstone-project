import json
import uuid
from langchain_core.messages import ToolMessage


def _parse_tool_json(msg: ToolMessage):
    try:
        return json.loads(msg.content)
    except Exception:
        return None


def _find_last_tool_payload(messages, tool_name: str):
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage) and getattr(msg, "name", "") == tool_name:
            return _parse_tool_json(msg)
    return None


def _is_last_message_from_tool(messages, tool_name: str) -> bool:
    if not messages:
        return False
    last = messages[-1]
    return isinstance(last, ToolMessage) and getattr(last, "name", "") == tool_name


def _guess_field_type(label: str) -> str:
    l = (label or "").lower()
    if "ngày" in l or "tháng" in l or "năm" in l:
        return "date"
    if "điện thoại" in l or "số điện thoại" in l:
        return "tel"
    if "địa chỉ" in l or "nơi ở" in l:
        return "textarea"
    if "số" in l and ("cmnd" in l or "cccd" in l or "định danh" in l):
        return "text"
    return "text"


def _build_dynamic_form_payload(fields: list[dict], pdf_path: str | None) -> dict:
    return {
        "kind": "dynamic_form",
        "request_id": str(uuid.uuid4()),
        "title": "Vui lòng điền thông tin vào biểu mẫu",
        "description": "Các trường dưới đây được trích xuất tự động từ mẫu đơn.",
        "submit_label": "Tiếp tục điền đơn",
        "pdf_path": pdf_path,
        "fields": [
            {
                "field_id": f["field_id"],
                "label": f["label"],
                "type": _guess_field_type(f["label"]),
                "required": True,
                "placeholder": f"Nhập {f['label'].lower()}",
                "x": f.get("x"),
                "y": f.get("y"),
            }
            for f in fields
        ],
    }
