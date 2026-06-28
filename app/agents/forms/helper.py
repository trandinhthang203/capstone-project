import json
import unicodedata
import uuid
from datetime import date, datetime
from typing import Any
import re
from langchain_core.messages import ToolMessage


SELF_FIELD_EXCLUSION_KEYWORDS = [
    "cha",
    "me",
    "mẹ",
    "vo",
    "vợ",
    "chong",
    "chồng",
    "con",
    "nguoi than",
    "người thân",
    "than nhan",
    "thân nhân",
    "giam ho",
    "giám hộ",
    "dai dien",
    "đại diện",
]

PROFILE_LABEL_RULES: list[tuple[str, list[str]]] = [
    ("citizenid", ["so dinh danh", "dinh danh ca nhan", "cccd", "cmnd", "can cuoc"]),
    ("dateofbirth", ["ngay sinh", "sinh ngay", "nam sinh"]),
    ("phonenumber", ["so dien thoai", "dien thoai", "di dong", "sdt", "mobile"]),
    ("gender", ["gioi tinh", "nam/nu", "nam nu"]),
    ("province", ["tinh/thanh pho", "tinh/thanh", "tinh thanh", "thanh pho", "tinh"]),
    ("district", ["quan/huyen", "quan huyen", "quận/huyện", "huyen", "quan"]),
    ("ward", ["phuong/xa", "phuong xa", "phường/xã", "xa", "phuong"]),
    (
        "address",
        [
            "dia chi thuong tru",
            "noi thuong tru",
            "cho o hien tai",
            "noi o hien tai",
            "dia chi lien he",
            "dia chi",
            "noi cu tru"
        ],
    ),
    (
        "fullname",
        [
            "ho va ten",
            "ho ten",
            "ho, chu dem va ten",
            "ten khai sinh",
            "nguoi khai",
            "nguoi yeu cau",
            "nguoi de nghi",
            "cong dan",
        ],
    ),
]

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



def _normalize_text(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().replace("_", " ").split())



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



def _compose_full_address(user_profile: dict[str, Any]) -> str:
    ordered_parts: list[str] = []
    for key in ("address", "ward", "district", "province"):
        value = str(user_profile.get(key) or "").strip()
        if value and value not in ordered_parts:
            ordered_parts.append(value)
    return ", ".join(ordered_parts)



def _format_date(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")

    text = str(value).strip()
    if not text:
        return ""

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.strftime("%d/%m/%Y")
        except ValueError:
            continue
    return text



def _format_gender(value: Any) -> str:
    raw = str(value or "").strip().lower()
    mapping = {
        "male": "Nam",
        "female": "Nữ",
        "other": "Khác",
        "nam": "Nam",
        "nữ": "Nữ",
        "nu": "Nữ",
    }
    return mapping.get(raw, str(value or "").strip())



def _is_non_self_field(label: str) -> bool:
    normalized = _normalize_text(label)
    explicit_self_markers = ["nguoi khai", "nguoi yeu cau", "nguoi de nghi", "cong dan", "chu don"]
    if any(marker in normalized for marker in explicit_self_markers):
        return False
    return any(keyword in normalized for keyword in SELF_FIELD_EXCLUSION_KEYWORDS)



def _match_profile_key(label: str) -> str | None:
    normalized = _normalize_text(label)
    if not normalized or _is_non_self_field(normalized):
        return None

    for profile_key, keywords in PROFILE_LABEL_RULES:
        if any(keyword in normalized for keyword in keywords):
            return profile_key
    return None



def _resolve_profile_value(profile_key: str, user_profile: dict[str, Any]) -> str:
    if not user_profile:
        return ""

    if profile_key == "address":
        return _compose_full_address(user_profile)
    if profile_key == "dateofbirth":
        return _format_date(user_profile.get("dateofbirth"))
    if profile_key == "gender":
        return _format_gender(user_profile.get("gender"))

    value = user_profile.get(profile_key)
    return str(value).strip() if value is not None else ""



def enrich_fields_with_profile(fields: list[dict], user_profile: dict[str, Any] | None) -> list[dict]:
    if not user_profile:
        return fields

    enriched_fields: list[dict] = []
    for field in fields:
        cloned = dict(field)
        profile_key = _match_profile_key(str(field.get("label") or ""))
        if profile_key:
            value = _resolve_profile_value(profile_key, user_profile)
            if value:
                cloned["value"] = value
                cloned["prefill_source"] = "user_profile"
                cloned["prefill_key"] = profile_key
        enriched_fields.append(cloned)

    return enriched_fields



def extract_prefill_values(fields: list[dict]) -> dict[str, str]:
    prefill_values: dict[str, str] = {}
    for field in fields:
        value = field.get("value")
        if value is None:
            continue
        text = str(value).strip()
        if text:
            prefill_values[str(field.get("field_id"))] = text
    return prefill_values



def _build_dynamic_form_payload(
    fields: list[dict],
    pdf_path: str | None,
    user_profile: dict[str, Any] | None = None,
) -> dict:
    enriched_fields = enrich_fields_with_profile(fields, user_profile)
    return {
        "kind": "dynamic_form",
        "request_id": str(uuid.uuid4()),
        "title": "Vui lòng điền thông tin vào biểu mẫu",
        "description": "Các trường dưới đây được trích xuất tự động từ mẫu đơn. Những trường đã có dữ liệu từ hồ sơ người dùng sẽ được điền sẵn và bạn vẫn có thể chỉnh sửa.",
        "submit_label": "Tiếp tục điền đơn",
        "pdf_path": pdf_path,
        "fields": [
            {
                "field_id": f["field_id"],
                "label": f["label"],
                "type": _guess_field_type(f["label"]),
                "required": True,
                "placeholder": f"Nhập {f['label'].lower()}",
                "value": f.get("value"),
                "prefill_source": f.get("prefill_source"),
                "prefill_key": f.get("prefill_key"),
                "x": f.get("x"),
                "y": f.get("y"),
                "page": int(f.get("page", 0) or 0),
            }
            for f in enriched_fields
        ],
    }
