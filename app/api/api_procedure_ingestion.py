from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.permissions import require_roles
from app.db.session import get_db
from app.models.user import User
from app.schemas.procedure_ingestion import ProcessDraftsRequest, PublishProceduresRequest
from scripts.ingestion.pipeline import check_and_import, process_drafts, publish_archived


router = APIRouter()
ingestion_user = require_roles("admin", "editor")


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.post("/check-and-import")
def import_new_procedures(
    excel_file: UploadFile = File(...),
    sheet_name: str = Form("0"),
    db: Session = Depends(get_db),
    current_user: User = Depends(ingestion_user),
):
    suffix = Path(excel_file.filename or "procedures.xlsx").suffix.lower()
    if suffix not in {".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="File phải có định dạng .xlsx hoặc .xls")
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
            temp_path = temp.name
            while chunk := excel_file.file.read(1024 * 1024):
                temp.write(chunk)
        sheet: str | int = int(sheet_name) if sheet_name.isdigit() else sheet_name
        return check_and_import(temp_path, current_user.id, db=db, sheet_name=sheet)
    except (ValueError, PermissionError) as exc:
        raise _bad_request(exc) from exc
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)
        excel_file.file.close()


@router.post("/process-drafts")
def process_procedure_drafts(
    request: ProcessDraftsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(ingestion_user),
):
    try:
        return process_drafts(
            current_user.id,
            procedure_ids=request.procedure_ids,
            filters=request.filters(),
            db=db,
        )
    except (ValueError, PermissionError) as exc:
        raise _bad_request(exc) from exc


@router.post("/publish")
def publish_procedures(
    request: PublishProceduresRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(ingestion_user),
):
    try:
        return publish_archived(
            current_user.id,
            procedure_ids=request.procedure_ids,
            filters=request.filters(),
            db=db,
            batch_size=request.batch_size,
        )
    except (ValueError, PermissionError) as exc:
        raise _bad_request(exc) from exc
