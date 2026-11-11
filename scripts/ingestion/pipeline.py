"""Điều phối luồng nhập, chuẩn hóa và indexing thủ tục hành chính.

Luồng được tách làm hai pha để phù hợp với thao tác của editor trên giao diện:

1. ``check_and_import`` đọc Excel, đối chiếu theo mã và tạo các bản ghi DRAFT mới.
2. ``process_drafts`` upload tài liệu của các bản ghi DRAFT, parse từ URL đã
   upload, lưu dữ liệu có cấu trúc, chuyển sang ARCHIVED và index.
3. ``publish_archived`` chuyển cả bản ghi database và point Qdrant sang PUBLISHED.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session, joinedload

from app.db.session import SessionLocal
from app.models.basis import Basis
from app.models.component import Component
from app.models.component_document import ComponentDocument
from app.models.method import Method
from app.models.procedure import Procedure
from app.models.procedure_group import ProcedureGroup, ProcedureGroupStatus
from app.models.user import User
from scripts.ingestion.indexing import update_procedure_status, upsert_procedures
from scripts.ingestion.parsing import parse_pdf
from scripts.ingestion.preprocesing import find_new_procedures
from scripts.ingestion.seed_database import (
    DEFAULT_DRIVER_PATH,
    make_driver,
    make_s3_client,
    safe_name,
    scrape_procedure,
    upload_file,
)


def _uuid(value: str | uuid.UUID, field: str = "user_id") -> uuid.UUID:
    """Kiểm tra giá trị id này có phải là UUID hợp lệ hay không"""
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{field} phải là UUID hợp lệ") from exc


def _require_editor(db: Session, user_id: str | uuid.UUID) -> User:
    """Trả về admin/editor đang hoạt động, nếu không thì từ chối."""
    editor = (
        db.query(User)
        .options(joinedload(User.role))
        .filter(User.id == _uuid(user_id), User.is_active.is_(True))
        .one_or_none()
    )
    if editor is None:
        raise PermissionError("Không tìm thấy editor đang hoạt động")
    if editor.role is None or editor.role.code.casefold() not in {"admin", "editor"}:
        raise PermissionError("Chỉ admin hoặc editor được chạy ingestion")
    return editor


def _apply_group_filters(query: Any, filters: Mapping[str, str] | None) -> Any:
    """Áp dụng các bộ lọc thủ tục được API hỗ trợ."""
    if not filters:
        return query
    allowed = {"issuing_agency", "domain", "implementing_agency"}
    invalid = set(filters) - allowed
    if invalid:
        raise ValueError(f"Trường filter không hợp lệ: {', '.join(sorted(invalid))}")
    for field, value in filters.items():
        if value:
            query = query.filter(getattr(ProcedureGroup, field) == value)
    return query


def preview_new_procedures(
    excel_file: str | Path,
    user_id: str | uuid.UUID,
    db: Session | None = None,
    sheet_name: str | int = 0,
) -> list[dict[str, str | None]]:
    """Đối chiếu Excel với bảng procedures mà không thay đổi database."""
    owns_session = db is None
    session = db or SessionLocal()
    try:
        _require_editor(session, user_id)
        return find_new_procedures(excel_file, db=session, sheet_name=sheet_name)
    finally:
        if owns_session:
            session.close()


def check_and_import(
    excel_file: str | Path,
    user_id: str | uuid.UUID,
    db: Session | None = None,
    sheet_name: str | int = 0,
) -> dict[str, Any]:
    """Chỉ thêm các thủ tục mới từ Excel dưới trạng thái DRAFT."""
    owns_session = db is None
    session = db or SessionLocal()
    try:
        editor = _require_editor(session, user_id)
        rows = find_new_procedures(excel_file, db=session, sheet_name=sheet_name)
        created = [
            ProcedureGroup(
                user_id=editor.id,
                **row,
                status=ProcedureGroupStatus.DRAFT,
                page_url=None,
                document_url=None,
            )
            for row in rows
        ]
        session.add_all(created)
        session.commit()
        return {
            "new_count": len(created),
            "procedures": [
                {"id": str(item.id), "code": item.code, "name": item.name}
                for item in created
            ],
        }
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


def _replace_structured_version(group: ProcedureGroup, parsed: Mapping[str, Any]) -> None:
    """Thay phiên bản cấu trúc của một group bằng kết quả parsing mới nhất."""
    data = dict(parsed)
    parsed_code = data.pop("code", None)
    if parsed_code and str(parsed_code).strip() != group.code:
        raise ValueError(
            f"Mã trong tài liệu ({parsed_code}) không khớp mã thủ tục ({group.code})"
        )

    previous = max(group.versions, key=lambda item: item.created_at) if group.versions else None
    previous_page_url = (previous.page_url if previous else None) or group.page_url
    previous_document_url = (previous.document_url if previous else None) or group.document_url
    previous_form_urls = list(previous.form_urls or []) if previous else []

    components = data.pop("components", []) or []
    methods = data.pop("methods", []) or []
    bases = data.pop("bases", []) or []
    group.versions.clear()

    procedure_fields = {column.name for column in Procedure.__table__.columns}
    values = {
        key: value
        for key, value in data.items()
        if key in procedure_fields and key not in {"id", "procedure_id", "created_at", "updated_at"}
    }
    values["name"] = values.get("name") or group.name
    values["page_url"] = values.get("page_url") or previous_page_url
    values["document_url"] = values.get("document_url") or previous_document_url
    values["form_urls"] = values.get("form_urls") or previous_form_urls
    version = Procedure(**values)
    version.methods = [Method(**item) for item in methods]
    version.bases = [Basis(**item) for item in bases]
    version.components = []
    for item in components:
        component_data = dict(item)
        documents = component_data.pop("documents", []) or []
        component = Component(**component_data)
        component.documents = [ComponentDocument(**document) for document in documents]
        version.components.append(component)
    group.versions.append(version)

    group.page_url = version.page_url
    group.document_url = version.document_url
    group.status = ProcedureGroupStatus.ARCHIVED


def process_drafts(
    user_id: str | uuid.UUID,
    sources: Mapping[str, str | Path | bytes] | None = None,
    procedure_ids: Sequence[str | uuid.UUID] | None = None,
    filters: Mapping[str, str] | None = None,
    db: Session | None = None,
    headless: bool = False,
    driver_path: str | None = DEFAULT_DRIVER_PATH,
    timeout: int = 25,
) -> dict[str, Any]:
    """Crawl, parse, chuyển DRAFT sang ARCHIVED và index các point Qdrant.

    Mặc định, PDF chi tiết và mẫu đơn được crawl bằng pipeline trong
    ``seed_database.py``. ``sources`` là đầu vào PDF thay thế tùy chọn; parser
    luôn nhận URL của tài liệu sau khi upload.
    """
    owns_session = db is None
    session = db or SessionLocal()
    try:
        _require_editor(session, user_id)
        query = session.query(ProcedureGroup).filter(
            ProcedureGroup.status == ProcedureGroupStatus.DRAFT,
        )
        if procedure_ids is not None:
            ids = [_uuid(item, "procedure_id") for item in procedure_ids]
            if not ids:
                return {"processed": 0, "indexed": 0, "codes": []}
            query = query.filter(ProcedureGroup.id.in_(ids))
        query = _apply_group_filters(query, filters)
        groups = query.order_by(ProcedureGroup.created_at).all()

        processed_ids: list[uuid.UUID] = []
        codes: list[str] = []
        indexed = 0
        if groups:
            s3, bucket, region = make_s3_client()
        driver = None
        with tempfile.TemporaryDirectory(prefix="dvc-pipeline-") as temp_name:
            temp_dir = Path(temp_name)
            try:
                for group in groups:
                    source = sources.get(group.code) if sources is not None else None
                    page_url = group.page_url
                    form_urls: list[str] = []

                    if source is None:
                        if driver is None:
                            driver = make_driver(temp_dir, headless, driver_path)
                        scraped = scrape_procedure(driver, group.code, temp_dir, timeout)
                        source_path = scraped.detail_pdf
                        page_url = scraped.page_url
                        form_urls = list(dict.fromkeys(scraped.form_links))
                    elif isinstance(source, bytes):
                        source_path = temp_dir / f"{safe_name(group.code)}.pdf"
                        source_path.write_bytes(source)
                        scraped = None
                    elif str(source).lower().startswith(("http://", "https://")):
                        response = requests.get(str(source), timeout=(10, 60))
                        response.raise_for_status()
                        source_path = temp_dir / f"{safe_name(group.code)}.pdf"
                        source_path.write_bytes(response.content)
                        scraped = None
                    else:
                        source_path = Path(source)
                        if not source_path.is_file():
                            raise FileNotFoundError(
                                f"Không tìm thấy PDF cho thủ tục {group.code}: {source_path}"
                            )
                        scraped = None

                    prefix = f"procedures/{safe_name(group.code)}"
                    document_url = upload_file(
                        s3,
                        bucket,
                        region,
                        source_path,
                        f"{prefix}/detail/{safe_name(source_path.name, 'detail.pdf')}",
                    )
                    if scraped is not None:
                        for number, form_path in enumerate(scraped.form_files, 1):
                            form_urls.append(
                                upload_file(
                                    s3,
                                    bucket,
                                    region,
                                    form_path,
                                    f"{prefix}/forms/{number:02d}-{safe_name(form_path.name)}",
                                )
                            )
                    form_urls = list(dict.fromkeys(form_urls))

                    result = parse_pdf(document_url)
                    if "procedure" not in result:
                        raise ValueError(f"Parser không trả về procedure cho mã {group.code}")
                    parsed = dict(result["procedure"])
                    parsed.update(
                        page_url=page_url,
                        document_url=document_url,
                        form_urls=form_urls,
                    )
                    _replace_structured_version(group, parsed)

                    # Autoflush giúp upsert_procedures nhìn thấy trạng thái ARCHIVED
                    # trong cùng session trước khi transaction được commit.
                    result = upsert_procedures(
                        db=session,
                        procedure_ids=[group.id],
                    )
                    indexed += int(result["upserted"])
                    session.commit()
                    processed_ids.append(group.id)
                    codes.append(group.code)
            finally:
                if driver is not None:
                    driver.quit()
        return {
            "processed": len(processed_ids),
            "indexed": indexed,
            "codes": codes,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


def publish_archived(
    user_id: str | uuid.UUID,
    procedure_ids: Sequence[str | uuid.UUID] | None = None,
    filters: Mapping[str, str] | None = None,
    db: Session | None = None,
    batch_size: int = 64,
) -> dict[str, Any]:
    """Chuyển các thủ tục ARCHIVED trong database và Qdrant sang PUBLISHED."""
    owns_session = db is None
    session = db or SessionLocal()
    try:
        _require_editor(session, user_id)
        query = session.query(ProcedureGroup).filter(
            ProcedureGroup.status == ProcedureGroupStatus.ARCHIVED
        )
        if procedure_ids is not None:
            ids = [_uuid(item, "procedure_id") for item in procedure_ids]
            if not ids:
                return {"published": 0, "codes": []}
            query = query.filter(ProcedureGroup.id.in_(ids))
        query = _apply_group_filters(query, filters)
        groups = query.order_by(ProcedureGroup.code).all()
        if not groups:
            return {"published": 0, "codes": []}
        update_procedure_status(
            [group.id for group in groups],
            ProcedureGroupStatus.PUBLISHED,
            batch_size=batch_size,
        )
        for group in groups:
            group.status = ProcedureGroupStatus.PUBLISHED
        session.commit()
        return {
            "published": len(groups),
            "codes": [group.code for group in groups],
        }
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


def _load_sources(path: Path | None) -> dict[str, str] | None:
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise ValueError("sources JSON phải có dạng {\"mã thủ tục\": \"URL/path PDF\"}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Pipeline ingestion thủ tục hành chính")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Đối chiếu và nhập thủ tục mới từ Excel")
    check.add_argument("excel_file", type=Path)
    check.add_argument("--user-id", required=True)
    check.add_argument("--sheet", default=0)

    process = subparsers.add_parser("process", help="Parse DRAFT rồi lưu thành ARCHIVED")
    process.add_argument("--user-id", required=True)
    process.add_argument("--procedure-id", action="append", dest="procedure_ids")
    process.add_argument("--sources", type=Path, help="File JSON tùy chọn ánh xạ code sang PDF")
    process.add_argument("--timeout", type=int, default=25)
    process.add_argument("--driver-path", default=DEFAULT_DRIVER_PATH)
    process.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    if args.command == "check":
        # result = check_and_import(args.excel_file, args.user_id, sheet_name=args.sheet)
        pass
    else:
        result = process_drafts(
            args.user_id,
            sources=_load_sources(args.sources),
            procedure_ids=args.procedure_ids,
            timeout=args.timeout,
            driver_path=args.driver_path,
            headless=args.headless,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
