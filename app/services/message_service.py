import asyncio
import json
from contextlib import suppress
from uuid import UUID

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.agents.base.state import AgentState, StreamEvent
from app.agents.base.utils import reset_queue, set_queue
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.schemas.chat_message import ChatMessageCreate, DynamicFormSubmitRequest


class _StreamEventError(Exception):
    pass


class MessageService(object):
    def __init__(self, db: Session, user_id: str | None = None):
        self.db = db
        self.app = None
        self.user_id = user_id

    def _build_config(self, session_id: UUID):
        return {
            "configurable": {
                "thread_id": str(session_id),
                "user_id": self.user_id,
            }
        }

    def _get_user_role(self) -> str:
        from app.models.user import User
        user = self.db.query(User).filter(User.id == self.user_id).first()
        return user.role.code.upper() if user and user.role else "USER"

    def ensure_session_access(self, session_id: UUID) -> ChatSession:
        session = self.db.query(ChatSession).filter(
            ChatSession.id == session_id,
            ChatSession.user_id == self.user_id,
        ).first()
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="Không tìm thấy cuộc trò chuyện")
        return session

    def _save_message(self, session_id, content, isfromuser, msgtype="text", metadata=None):
        msg = ChatMessage(session_id=session_id, content=content,
                          role="user" if isfromuser else "assistant",
                          metadata_=({"message_type": msgtype, **(metadata or {})}))
        self.db.add(msg)
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def _extract_interrupt_payload(self, result: dict):
        interrupts = result.get("__interrupt__") or []
        if not interrupts:
            return None
        first = interrupts[0]
        return first.value if hasattr(first, "value") else first

    async def create_message_stream(self, data: ChatMessageCreate):
        self._save_message(
            session_id=data.idchatsession,
            content=data.msgcontent,
            isfromuser=True,
            msgtype="text",
        )
        config = self._build_config(data.idchatsession)
        state: AgentState = {
            "messages": [HumanMessage(content=data.msgcontent)],
            "user_input": data.msgcontent,
            "user_id": self.user_id,
            "session_id": str(data.idchatsession),
            "user_role": self._get_user_role(),
        }


 
