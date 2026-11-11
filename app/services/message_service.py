import asyncio
import json
from dataclasses import asdict
from typing import Any, AsyncIterator
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

    @staticmethod
    def _sse(event: str, data: Any) -> str:
        """Serialize one Server-Sent Event block."""
        payload = json.dumps(data, ensure_ascii=False, default=str)
        return f"event: {event}\ndata: {payload}\n\n"

    @staticmethod
    def _snapshot_interrupt_payload(snapshot: Any) -> dict[str, Any] | None:
        """Read the pending interrupt from a LangGraph StateSnapshot."""
        for task in getattr(snapshot, "tasks", ()):
            for item in getattr(task, "interrupts", ()):
                value = item.value if hasattr(item, "value") else item
                if isinstance(value, dict):
                    return value
        return None

    async def validate_resume(self, data: DynamicFormSubmitRequest) -> None:
        """Fail before StreamingResponse starts if this form cannot be resumed."""
        if self.app is None:
            raise RuntimeError("Workflow chưa được gán cho MessageService")

        snapshot = await self.app.aget_state(self._build_config(data.idchatsession))
        if not snapshot.values:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy trạng thái hội thoại để tiếp tục",
            )
        if not snapshot.next:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Luồng xử lý này đã hoàn thành hoặc không chờ phản hồi",
            )

        payload = self._snapshot_interrupt_payload(snapshot)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Luồng xử lý hiện tại không có interrupt đang chờ",
            )
        if payload.get("request_id") != data.request_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="request_id không khớp với form đang chờ",
            )

    async def _run_graph_stream(
        self,
        graph_input: AgentState | Command,
        session_id: UUID,
    ) -> AsyncIterator[str]:
        """Run LangGraph while forwarding node events as SSE."""
        if self.app is None:
            yield self._sse("error", {"message": "Workflow chưa được khởi tạo"})
            return

        queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        config = self._build_config(session_id)

        async def invoke() -> dict[str, Any]:
            token = set_queue(queue)
            try:
                return await self.app.ainvoke(graph_input, config=config)
            finally:
                reset_queue(token)
                await queue.put(None)

        task = asyncio.create_task(invoke())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                event_data = asdict(event)
                yield self._sse(event.type, event_data)

            result = await task
            interrupt_payload = self._extract_interrupt_payload(result)
            if interrupt_payload is not None:
                self._save_message(
                    session_id=session_id,
                    content=str(
                        interrupt_payload.get("description")
                        or interrupt_payload.get("title")
                        or "Cần thêm thông tin"
                    ),
                    isfromuser=False,
                    msgtype="dynamic_form",
                    metadata={"form": interrupt_payload},
                )
                yield self._sse("interrupt", interrupt_payload)
                return

            answer = str(result.get("final_answer") or "")
            if answer:
                self._save_message(
                    session_id=session_id,
                    content=answer,
                    isfromuser=False,
                    msgtype="text",
                )
            yield self._sse(
                "done",
                {"message": answer, "status": "completed"},
            )
        except asyncio.CancelledError:
            task.cancel()
            raise
        except Exception as exc:
            if not task.done():
                task.cancel()
            yield self._sse("error", {"message": str(exc)})

    async def create_message_stream(self, data: ChatMessageCreate):
        self._save_message(
            session_id=data.idchatsession,
            content=data.msgcontent,
            isfromuser=True,
            msgtype="text",
        )
        state: AgentState = {
            "messages": [HumanMessage(content=data.msgcontent)],
            "user_input": data.msgcontent,
            "user_id": self.user_id,
            "session_id": str(data.idchatsession),
            "user_role": self._get_user_role(),
        }

        async for event in self._run_graph_stream(state, data.idchatsession):
            yield event

    async def resume_message_stream(self, data: DynamicFormSubmitRequest):
        """Persist the submitted form and resume the pending interrupt."""
        self._save_message(
            session_id=data.idchatsession,
            content=json.dumps(data.values, ensure_ascii=False, default=str),
            isfromuser=True,
            msgtype="dynamic_form_response",
            metadata={
                "request_id": data.request_id,
                "values": data.values,
            },
        )

        command = Command(resume=data.values)
        async for event in self._run_graph_stream(command, data.idchatsession):
            yield event
