"""Import danh sách thủ tục hành chính từ Excel vào bảng ``procedures``."""

from __future__ import annotations

import argparse
import math
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.procedure_group import ProcedureGroup, ProcedureGroupStatus


EXCEL_COLUMNS = {
    "Mã số": "code",
    "Tên": "name",
    "Cơ quan ban hành": "issuing_agency",
    "Cơ quan thực hiện": "implementing_agency",
    "Lĩnh vực": "domain",
}


def _clean_value(value: Any) -> str | None:
    """Chuẩn hóa ô trống và khoảng trắng, kể cả nội dung nhiều dòng."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    text = " ".join(str(value).split())
    return text or None


def _clean_code(value: Any) -> str | None:
    """Chuyển mã thủ tục thành chuỗi mà không tạo hậu tố ``.0`` giả."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return str(int(value))
        return format(value, ".15g")
    return _clean_value(value)


def _find_header_row(file_path: str | Path, sheet_name: str | int = 0) -> int:
    """Tìm dòng tiêu đề vì phía trên bảng có thể có quốc hiệu/tên báo cáo."""
    preview = pd.read_excel(file_path, sheet_name=sheet_name, header=None, dtype=object)
    expected = set(EXCEL_COLUMNS)
    for index, row in preview.iterrows():
        values = {_clean_value(value) for value in row.tolist()}
        if expected.issubset(values):
            return int(index)
    raise ValueError(
        "Không tìm thấy dòng tiêu đề gồm: " + ", ".join(EXCEL_COLUMNS)
    )


def read_procedures_excel(
    file_path: str | Path, sheet_name: str | int = 0
) -> list[dict[str, str | None]]:
    """Đọc và chuẩn hóa các dòng dữ liệu từ file Excel."""
    file_path = Path(file_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file Excel: {file_path}")

    header_row = _find_header_row(file_path, sheet_name)
    frame = pd.read_excel(
        file_path,
        sheet_name=sheet_name,
        header=header_row,
        dtype=object,
    )
    frame.columns = [_clean_value(column) for column in frame.columns]

    missing = [column for column in EXCEL_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"File Excel thiếu cột: {', '.join(missing)}")

    rows: list[dict[str, str | None]] = []
    seen_codes: set[str] = set()
    for _, source in frame[list(EXCEL_COLUMNS)].iterrows():
        code = _clean_code(source["Mã số"])
        name = _clean_value(source["Tên"])
        if code is None and name is None:  # Bỏ qua dòng trống cuối file.
            continue
        if code is None or name is None:
            raise ValueError("Mỗi dòng dữ liệu phải có đủ 'Mã số' và 'Tên'")
        if code in seen_codes:
            raise ValueError(f"Mã số bị trùng trong file Excel: {code}")
        seen_codes.add(code)

        row = {"code": code, "name": name}
        for excel_column, model_field in EXCEL_COLUMNS.items():
            if model_field not in row:
                row[model_field] = _clean_value(source[excel_column])
        rows.append(row)
    return rows


def import_procedures_excel(
    file_path: str | Path,
    user_id: str | uuid.UUID,
    db: Session | None = None,
    sheet_name: str | int = 0,
) -> dict[str, int]:
    """Thêm/cập nhật thủ tục theo mã và commit trong một transaction.

    Nếu ``db`` không được truyền, hàm tự tạo và đóng database session.
    """
    try:
        owner_id = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("user_id phải là UUID hợp lệ") from exc

    rows = read_procedures_excel(file_path, sheet_name)
    owns_session = db is None
    session = db or SessionLocal()
    created = updated = 0
    try:
        codes = [row["code"] for row in rows]
        existing = {
            item.code: item
            for item in session.query(ProcedureGroup)
            .filter(ProcedureGroup.code.in_(codes))
            .all()
        }
        for row in rows:
            procedure = existing.get(row["code"])
            if procedure is None:
                session.add(
                    ProcedureGroup(
                        user_id=owner_id,
                        **row,
                        status=ProcedureGroupStatus.DRAFT,
                        page_url=None,
                        document_url=None,
                    )
                )
                created += 1
            else:
                for field, value in row.items():
                    setattr(procedure, field, value)
                updated += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()
    return {"created": created, "updated": updated, "total": len(rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Import thủ tục hành chính từ Excel")
    parser.add_argument("excel_file", type=Path)
    parser.add_argument("--user-id", required=True, help="UUID người sở hữu dữ liệu")
    parser.add_argument("--sheet", default=0, help="Tên sheet (mặc định: sheet đầu tiên)")
    args = parser.parse_args()

    result = import_procedures_excel(args.excel_file, args.user_id, sheet_name=args.sheet)
    print(
        f"Đã xử lý {result['total']} thủ tục: "
        f"thêm {result['created']}, cập nhật {result['updated']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
