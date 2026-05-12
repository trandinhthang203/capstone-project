from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.chat_message import ChatMessage
from app.schemas.chat_message import ChatMessageCreate, ChatMessageResponse
from fastapi import Depends
from app.db.session import get_db
from uuid import UUID
from app.agents.base.graph import create_workflow
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk
import asyncio
from app.agents.base.utils import set_queue
from app.agents.base.state import StreamEvent
import json
from app.agents.base.state import AgentState

class MessageService(object):
    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.app = None
        self.user_id = user_id
        self.full_response = ""
        self.config = {}

    async def initialize(self):
        self.app = await create_workflow()

# ─── CREATE ───

    async def create_message_stream(self, data: ChatMessageCreate):
        message = ChatMessage(
            idchatsession=data.idchatsession,
            msgcontent=data.msgcontent
        )
        self.db.add(message)
        self.db.commit()

        self.full_response = ""
        self.config = {
            "configurable": {
                "thread_id": data.idchatsession,
                "user_id":   self.user_id,
            }
        }

        queue = asyncio.Queue()
        set_queue(queue)

        graph_task = asyncio.create_task(
            self.app.ainvoke(
                {
                    "messages": [HumanMessage(content=data.msgcontent)],
                    "user_input": data.msgcontent,
                },
                self.config,
            )
        )

        while not graph_task.done() or not queue.empty():
            try:
                event: StreamEvent = await asyncio.wait_for(queue.get(), timeout=0.05)
            except asyncio.TimeoutError:
                continue

            if event.type == "progress":
                yield f"data: {json.dumps({'type': 'progress', 'node': event.node, 'message': event.message})}\n\n"

            elif event.type == "result":
                yield f"data: {json.dumps({'type': 'result', 'node': event.node, 'message': event.message or {}})}\n\n"

            elif event.type == "error":
                yield f"data: {json.dumps({'type': 'error', 'message': event.message})}\n\n"
                return

        result = await graph_task

        if not self.full_response:
            self.full_response = result.get("final_response", "") or ""
            yield f"data: {json.dumps({'type': 'result', 'answer': self.full_response})}\n\n"

        ai_message = ChatMessage(
            idchatsession=data.idchatsession,
            msgcontent=self.full_response,
            isfromuser=False
        )
        self.db.add(ai_message)
        self.db.commit()
        self.db.refresh(ai_message)

        yield f"data: {json.dumps({'type': 'done', 'idchatmessage': ai_message.idchatmessage})}\n\n"

       


    # ─── READ ─────

    # def get_sessions(self, user_id: int) -> list[ChatSessionResponse]:
    #     sessions = self.db.query(ChatSession).filter(ChatSession.iduser == user_id).all()
    #     return sessions


    # # ─── UPDATE ─────


    # # ─── DELETE ────────

    # def delete_session(self, session_id: UUID, user_id: int) -> ChatSessionResponse:
    #     session = self.db.query(ChatSession).filter(
    #         ChatSession.idchatsession == session_id,
    #         ChatSession.iduser == user_id         
    #     ).first()

    #     if not session:
    #         raise HTTPException(
    #             status_code=status.HTTP_404_NOT_FOUND,
    #             detail="Không tìm thấy cuộc trò chuyện này"
    #         )

    #     self.db.delete(session)
    #     self.db.commit()
    #     return session
