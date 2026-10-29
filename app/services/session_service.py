from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.schemas.chat_session import ChatSessionCreate


class SessionService:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    def create_session(self, data: ChatSessionCreate) -> ChatSession:
        session = ChatSession(user_id=data.user_id, title=data.title)
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_sessions(self, user_id: UUID) -> list[ChatSession]:
        return (self.db.query(ChatSession)
                .filter(ChatSession.user_id == user_id)
                .order_by(ChatSession.created_at.desc()).all())

    def get_details_session(self, session_id: UUID, user_id: UUID) -> list[ChatMessage]:
        session = self._owned_session(session_id, user_id)
        return (self.db.query(ChatMessage).filter(ChatMessage.session_id == session.id)
                .order_by(ChatMessage.created_at.asc()).all())

    def delete_session(self, session_id: UUID, user_id: UUID) -> ChatSession:
        session = self._owned_session(session_id, user_id)
        self.db.delete(session)
        self.db.commit()
        return session

    def _owned_session(self, session_id: UUID, user_id: UUID) -> ChatSession:
        session = (self.db.query(ChatSession)
                   .filter(ChatSession.id == session_id, ChatSession.user_id == user_id).first())
        if not session:
            # 404 không tiết lộ session có tồn tại nhưng thuộc người khác hay không.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="Không tìm thấy cuộc trò chuyện")
        return session
