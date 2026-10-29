from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.message_service import MessageService
from app.schemas.chat_message import ChatMessageCreate, ChatMessageResponse, DynamicFormSubmitRequest
from app.core.deps import get_current_user

router = APIRouter()

@router.post("/stream")
async def create_message_stream(
    request: Request,
    data: ChatMessageCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    service = MessageService(db, current_user.id)
    service.ensure_session_access(data.idchatsession)
    service.app = request.app.state.workflow

    return StreamingResponse(
        service.create_message_stream(data),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  
        }
    )

@router.post("/forms/submit")
async def submit_dynamic_form_stream(
    request: Request,
    data: DynamicFormSubmitRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    service = MessageService(db, current_user.id)
    service.ensure_session_access(data.idchatsession)
    service.app = request.app.state.workflow

    return StreamingResponse(
        service.submit_dynamic_form_stream(data),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )

