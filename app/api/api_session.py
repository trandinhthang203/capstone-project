from fastapi import APIRouter, Depends, Body, status
from app.schemas.chat_session import ChatSessionCreate
from app.core.deps import get_current_user
from app.models.user import User
from app.services.session_service import SessionService
from app.helpers.utils.exception import CustomException
import sys
from uuid import UUID

router = APIRouter()

@router.post("/new", status_code=status.HTTP_201_CREATED)
def create(
    current_user = Depends(get_current_user),  
    service: SessionService = Depends()
):
    data = ChatSessionCreate(
        user_id=current_user.id
    )
    return service.create_session(data)

@router.get("")
def get_sessions(
    current_user = Depends(get_current_user),  
    service: SessionService = Depends()
):
    return service.get_sessions(current_user.id)

@router.get("/{session_id}")
async def get_details_session(
    session_id: UUID,
    current_user = Depends(get_current_user),  
    service: SessionService = Depends() 
):
    return service.get_details_session(session_id, user_id=current_user.id)

@router.delete("/{session_id}")
def delete(
    session_id: UUID,
    current_user = Depends(get_current_user),  
    service: SessionService = Depends()
):
    return service.delete_session(session_id, user_id=current_user.id)
