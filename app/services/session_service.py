from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.chat_session import ChatSession
from app.models.chat_message import ChatMessage
from app.schemas.chat_session import ChatSessionCreate, ChatSessionResponse
from app.schemas.chat_message import ChatMessageResponse
from fastapi import Depends
from app.db.session import get_db
from uuid import UUID


class SessionService(object):
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

# ─── CREATE ───

    def create_session(self, data: ChatSessionCreate) -> ChatSessionResponse:

        session = ChatSession(
            iduser = data.iduser,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session


    # ─── READ ─────

    def get_sessions(self, user_id: int) -> list[ChatSessionResponse]:
        sessions = (
            self.db.query(ChatSession)
            .filter(ChatSession.iduser == user_id)
            .order_by(ChatSession.createddate.desc())
            .all()
        )
        return sessions

    def get_details_session(self, session_id: UUID, user_id: int) -> list[ChatMessageResponse]:
        session = (
            self.db.query(ChatSession)
            .filter(
                ChatSession.idchatsession == session_id,
                ChatSession.iduser == user_id
            )
            .first()
        )
        if not session:
            raise HTTPException(status_code=404, detail="Session không tồn tại hoặc không có quyền truy cập")

        messages = (
            self.db.query(ChatMessage)
            .filter(ChatMessage.idchatsession == session_id)
            .order_by(ChatMessage.sentat.asc())
            .all()
        )
        return messages


    # ─── UPDATE ─────


    # ─── DELETE ────────

    def delete_session(self, session_id: UUID, user_id: int) -> ChatSessionResponse:
        session = self.db.query(ChatSession).filter(
            ChatSession.idchatsession == session_id,
            ChatSession.iduser == user_id         
        ).first()

        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy cuộc trò chuyện này"
            )

        self.db.delete(session)
        self.db.commit()
        return session