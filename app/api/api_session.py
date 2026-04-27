from fastapi import APIRouter, Depends, Body, status
from app.schemas.chat_session import ChatSessionCreate
from app.helpers.utils.dependencies import get_current_user, require_roles
from app.models.user import User
from app.services.session_service import SessionService
from app.helpers.utils.exception import CustomException
import sys
from uuid import UUID

router = APIRouter()

@router.post("")
def create(
    current_user = Depends(get_current_user),  
    service: SessionService = Depends()
):
    data = ChatSessionCreate(
        iduser=current_user.iduser
    )
    return service.create_session(data)

@router.get("")
def get_sessions(
    current_user = Depends(get_current_user),  
    service: SessionService = Depends()
):
    return service.get_sessions(current_user.iduser)


@router.delete("/{session_id}")
def delete(
    session_id: UUID,
    current_user = Depends(get_current_user),  
    service: SessionService = Depends()
):
    return service.delete_session(session_id, user_id=current_user.iduser)