from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.message_service import MessageService
from app.schemas.chat_message import ChatMessageCreate, DynamicFormSubmitRequest
from app.core.deps import get_current_user

router = APIRouter()


def _stream_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }


@router.post("/chat")
async def chat(
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
        headers=_stream_headers(),
    )


@router.post("/chat/resume")
async def resume_chat(
    request: Request,
    data: DynamicFormSubmitRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Submit a dynamic form and resume the interrupted LangGraph thread."""
    service = MessageService(db, current_user.id)
    service.ensure_session_access(data.idchatsession)
    service.app = request.app.state.workflow

    # Validate before response streaming begins so HTTP 404/409 is preserved.
    await service.validate_resume(data)

    return StreamingResponse(
        service.resume_message_stream(data),
        media_type="text/event-stream",
        headers=_stream_headers(),
    )


