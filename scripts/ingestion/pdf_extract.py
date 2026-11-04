"""Trích xuất text + bảng từ PDF, chọn backend nhanh nhất đang có.

PyMuPDF (``fitz``) nhanh hơn pdfplumber khoảng một bậc độ lớn cho cả
``get_text`` lẫn phát hiện bảng, và tốn ít RAM hơn -> phù hợp máy 4GB.
Đặt ``PDF_BACKEND=plumber`` (hoặc ``backend="plumber"``) để quay lại hành vi cũ.

    python scripts/ingestion/pdf_extract.py path/to/file.pdf   # so sánh tốc độ
"""

from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path
from typing import Any

# pdfplumber mặc định dò bảng bằng "lines" nhưng vẫn thử nhiều tolerance;
# ghim tolerance cố định để nó không phải chạy lại nhiều lượt.
FAST_TABLE_SETTINGS = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "snap_tolerance": 3,
    "join_tolerance": 3,
    "edge_min_length": 3,
    "intersection_tolerance": 3,
    "text_x_tolerance": 3,
    "text_y_tolerance": 3,
}

Table = list[list[Any]]


def mupdf_available() -> bool:
    try:
        import fitz  # noqa: F401
    except Exception:
        return False
    return hasattr(fitz.Page, "find_tables")


def extract_with_mupdf(content: bytes) -> tuple[list[str], list[Table]]:
    import fitz

    texts: list[str] = []
    tables: list[Table] = []
    with fitz.open(stream=content, filetype="pdf") as doc:
        for page in doc:
            texts.append(page.get_text("text") or "")
            try:
                finder = page.find_tables()
            except Exception:
                continue
            for table in getattr(finder, "tables", []) or []:
                try:
                    rows = table.extract()
                except Exception:
                    continue
                if rows:
                    tables.append(rows)
    return texts, tables


def extract_with_plumber(content: bytes) -> tuple[list[str], list[Table]]:
    import pdfplumber

    texts: list[str] = []
    tables: list[Table] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            texts.append(page.extract_text() or "")
            tables.extend(page.extract_tables(FAST_TABLE_SETTINGS) or [])
    return texts, tables


def extract_pages(content: bytes, backend: str | None = None) -> tuple[list[str], list[Table]]:
    """Trả về ``(text từng trang, danh sách bảng)`` theo backend được chọn."""
    chosen = (backend or os.getenv("PDF_BACKEND") or "auto").lower()
    if chosen == "plumber":
        return extract_with_plumber(content)
    if chosen == "mupdf":
        return extract_with_mupdf(content)
    if mupdf_available():
        try:
            return extract_with_mupdf(content)
        except Exception:
            pass  # PDF lạ / lỗi font -> rơi về pdfplumber
    return extract_with_plumber(content)


if __name__ == "__main__":
    target = Path(sys.argv[1])
    data = target.read_bytes()
    for name in ("mupdf", "plumber"):
        started = time.perf_counter()
        try:
            texts, tables = extract_pages(data, name)
        except Exception as exc:  # pragma: no cover - CLI
            print(f"{name}: LỖI {exc}")
            continue
        print(f"{name}: {time.perf_counter() - started:6.2f}s | "
              f"{len(texts)} trang | {len(tables)} bảng")
