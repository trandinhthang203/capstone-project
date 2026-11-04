"""Parse PDF chi tiết thủ tục hành chính sang cấu trúc của các model ORM."""

import json
import re
from pathlib import Path
from typing import Any
import requests
from scripts.ingestion.pdf_extract import extract_pages



# Nhãn PDF -> thuộc tính app.models.procedure.Procedure. Mã thủ tục thuộc
# ProcedureGroup nên được trả riêng ở khóa ``code``.
PROCEDURE_FIELD_MAP = {
    "Tên thủ tục": "name",
    "Số quyết định": "decision_number",
    "Cấp thực hiện": "level",
    "Loại thủ tục": "procedure_type",
    "Lĩnh vực": "field",
    "Đối tượng thực hiện": "subject",
    "Cơ quan có thẩm quyền": "competent_authority",
    "Địa chỉ tiếp nhận HS": "reception_address",
    "Cơ quan được ủy quyền": "delegated_authority",
    "Cơ quan phối hợp": "coordinating_authority",
}

SECTION_MAP = {
    "TRÌNH TỰ THỰC HIỆN": "steps",
    "THÀNH PHẦN HỒ SƠ": None,
    "CÁCH THỨC THỰC HIỆN": None,
    "CĂN CỨ PHÁP LÝ": None,
    "CƠ QUAN THỰC HIỆN": "executing_authority",
    "YÊU CẦU, ĐIỀU KIỆN THỰC HIỆN": "requirements",
    "KẾT QUẢ XỬ LÝ": None,  
    "TỪ KHÓA": "keywords",
    "MÔ TẢ": "description",
}


def clean(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).replace("\x00", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def normalize_label(value: Any) -> str:
    """Chuẩn hóa nhãn, chịu được khác biệt hoa/thường và dấu hai chấm."""
    return (clean(value) or "").casefold().rstrip(":").strip()


NORMALIZED_FIELDS = {
    normalize_label(label): key for label, key in PROCEDURE_FIELD_MAP.items()
}
NORMALIZED_SECTIONS = {
    normalize_label(label): value for label, value in SECTION_MAP.items()
}


def _extract_text_sections(pages: list[str]) -> dict[str, Any]:
    """Cắt nội dung giữa các tiêu đề, kể cả khi phần kéo dài qua trang."""
    values: dict[str, Any] = {}
    current_key: str | None = None
    chunks: list[str] = []

    def flush() -> None:
        nonlocal chunks
        if current_key is not None:
            value = clean("\n".join(chunks))
            if current_key == "keywords":
                values[current_key] = (
                    [item.strip() for item in re.split(r"[,;\n]+", value) if item.strip()]
                    if value else []
                )
            else:
                values[current_key] = value
        chunks = []

    for page_text in pages:
        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            normalized = normalize_label(line)
            if normalized in NORMALIZED_SECTIONS:
                flush()
                current_key = NORMALIZED_SECTIONS[normalized]
            elif current_key is not None:
                chunks.append(line)
    flush()
    return values


def _case_title(value: Any) -> str | None:
    title = clean(value)
    return None if title in {None, "--", "-", "—"} else title


def _is_case_row(first: str) -> bool:
    return bool(re.match(r"^trường\s+hợp(?:\s+\d+)?\s*:", first, re.IGNORECASE))


def _append_table_rows(procedure: dict[str, Any], tables: list[list[list[Any]]]) -> None:
    section: str | None = None
    current_component: dict[str, Any] | None = None
    component_headers = {"tên giấy tờ", "tên thành phần hồ sơ"}
    method_headers = {"hình thức nộp", "cách thức thực hiện"}
    basis_headers = {"tên văn bản pháp lý", "tên văn bản"}

    for table in tables:
        for raw_row in table:
            row = [clean(cell) for cell in raw_row]
            if not any(row):
                continue
            first = row[0] or ""
            label = normalize_label(first)

            if label in NORMALIZED_FIELDS and len(row) >= 2:
                procedure[NORMALIZED_FIELDS[label]] = row[1]
                section = None
                continue
            if label == "mã thủ tục" and len(row) >= 2:
                procedure["code"] = row[1]
                continue
            if _is_case_row(first):
                section = "components"
                current_component = {"title": _case_title(first), "documents": []}
                procedure["components"].append(current_component)
                continue
            if label in component_headers:
                section = "components"
                if current_component is None:
                    current_component = {"title": None, "documents": []}
                    procedure["components"].append(current_component)
                continue
            if label in method_headers:
                section = "methods"
                current_component = None
                continue
            if label in basis_headers:
                section = "bases"
                current_component = None
                continue

            if section == "components" and len(row) >= 3 and first:
                if current_component is None:
                    current_component = {"title": None, "documents": []}
                    procedure["components"].append(current_component)
                current_component["documents"].append({
                    "name": row[0], "form_name": row[1],
                    "form_url": None, "quantity": row[2],
                })
            elif section == "methods" and len(row) >= 4 and first:
                procedure["methods"].append({
                    "method_type": row[0], "processing_time": row[1],
                    "fee": row[2], "description": row[3],
                })
            elif section == "bases" and len(row) >= 2 and first:
                procedure["bases"].append({
                    "document_name": row[0], "document_code": row[1],
                })


def parse_pdf(
        source: str | Path | bytes, backend: str | None = None
    ) -> dict[str, dict[str, Any]]:
    """Parse URL, đường dẫn hoặc bytes PDF thành dữ liệu khớp các model ORM.

    ``procedure_id`` không được điền vì khóa ngoại này chỉ có sau khi caller
    xác định/tạo ProcedureGroup.
    """
    document_url: str | None = None
    if isinstance(source, bytes):
        content = source
    elif isinstance(source, Path) or not str(source).lower().startswith(("http://", "https://")):
        content = Path(source).read_bytes()
    else:
        document_url = str(source)
        response = requests.get(document_url, timeout=(10, 60))
        response.raise_for_status()
        content = response.content

    procedure: dict[str, Any] = {
        **{key: None for key in PROCEDURE_FIELD_MAP.values()},
        "executing_authority": None,
        "steps": None,
        "requirements": None,
        "description": None,
        "keywords": [],
        "page_url": None,
        "document_url": document_url,
        "form_urls": [],
        "components": [],
        "methods": [],
        "bases": [],
        "code": None,
    }

    page_texts, tables = extract_pages(content, backend)

    _append_table_rows(procedure, tables)
    procedure.update(_extract_text_sections(page_texts))
    procedure["components"] = [item for item in procedure["components"] if item["documents"]]
    if normalize_label(procedure.get("executing_authority")) == "không có thông tin":
        procedure["executing_authority"] = None
    return {"procedure": procedure}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parse PDF chi tiết thủ tục hành chính")
    parser.add_argument("source", help="URL hoặc đường dẫn PDF")
    args = parser.parse_args()
    print(json.dumps(parse_pdf(args.source), ensure_ascii=False, indent=2))
