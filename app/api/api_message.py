from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.message_service import MessageService
from app.schemas.chat_message import ChatMessageCreate, ChatMessageResponse, DynamicFormSubmitRequest
from app.helpers.utils.dependencies import get_current_user

router = APIRouter()

@router.post("/", response_model=ChatMessageResponse)
async def create_message(
    data: ChatMessageCreate,
    db: Session = Depends(get_db)
):
    service = MessageService(db)
    await service.initialize()  
    return await service.create_message(data)

@router.post("/stream")
async def create_message_stream(
    data: ChatMessageCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    service = MessageService(db, current_user.iduser)
    await service.initialize()

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
    data: DynamicFormSubmitRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    service = MessageService(db, current_user.iduser)
    await service.initialize()

    return StreamingResponse(
        service.submit_dynamic_form_stream(data),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )