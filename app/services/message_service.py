import asyncio
import json
from uuid import UUID

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from sqlalchemy.orm import Session

from app.agents.base.graph import create_workflow
from app.agents.base.state import AgentState, StreamEvent
from app.agents.base.utils import set_queue
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.schemas.chat_message import ChatMessageCreate, DynamicFormSubmitRequest


class MessageService(object):
    def __init__(self, db: Session, user_id: str | None = None):
        self.db = db
        self.app = None
        self.user_id = user_id
        self.full_response = ""
        self.config = {}

    async def initialize(self):
        self.app = await create_workflow()

    def _build_config(self, session_id: UUID):
        self.config = {
            "configurable": {
                "thread_id": str(session_id),
                "user_id": self.user_id,
            }
        }

    def _save_message(self, session_id, content, isfromuser, msgtype="text", metadata=None):
        msg = ChatMessage(
            idchatsession=session_id,
            msgcontent=content,
            isfromuser=isfromuser,
            msgtype=msgtype,
            meta_data=metadata,
        )
        self.db.add(msg)
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def _set_session_status(self, session_id, status: str):
        session = self.db.query(ChatSession).filter(ChatSession.idchatsession == session_id).first()
        if session:
            session.status = status
            self.db.commit()

    def _extract_interrupt_payload(self, result: dict):
        interrupts = result.get("__interrupt__") or []
        if not interrupts:
            return None
        first = interrupts[0]
        return first.value if hasattr(first, "value") else first

    def _get_latest_dynamic_form_message(self, session_id):
        return (
            self.db.query(ChatMessage)
            .filter(
                ChatMessage.idchatsession == session_id,
                ChatMessage.msgtype == "dynamic_form",
            )
            .order_by(ChatMessage.idchatmessage.desc())
            .first()
        )

    async def _stream_queue_events(self, queue, graph_task):
        while not graph_task.done() or not queue.empty():
            try:
                event: StreamEvent = await asyncio.wait_for(queue.get(), timeout=0.05)
            except asyncio.TimeoutError:
                continue

            if event.type == "progress":
                yield f"data: {json.dumps({'type': 'progress', 'node': event.node, 'message': event.message}, ensure_ascii=False)}\n\n"
            elif event.type == "result":
                yield f"data: {json.dumps({'type': 'result', 'node': event.node, 'message': event.message, 'data': event.data}, ensure_ascii=False)}\n\n"
            elif event.type == "error":
                yield f"data: {json.dumps({'type': 'error', 'message': event.message}, ensure_ascii=False)}\n\n"
                return

    async def create_message_stream(self, data: ChatMessageCreate):
        self._save_message(
            session_id=data.idchatsession,
            content=data.msgcontent,
            isfromuser=True,
            msgtype="text",
        )
        self._set_session_status(data.idchatsession, "RUNNING")
        self._build_config(data.idchatsession)

        queue = asyncio.Queue()
        set_queue(queue)

        state: AgentState = {
            "messages": [HumanMessage(content=data.msgcontent)],
            "user_input": data.msgcontent,
            "user_id": self.user_id,
        }

        graph_task = asyncio.create_task(self.app.ainvoke(state, self.config))

        try:
            async for chunk in self._stream_queue_events(queue, graph_task):
                yield chunk

            result = await graph_task
            interrupt_payload = self._extract_interrupt_payload(result)
            if interrupt_payload:
                self._save_message(
                    session_id=data.idchatsession,
                    content="Cần thêm dữ liệu để tiếp tục.",
                    isfromuser=False,
                    msgtype="dynamic_form",
                    metadata=interrupt_payload,
                )
                self._set_session_status(data.idchatsession, "WAITING_FORM_INPUT")
                yield f"data: {json.dumps({'type': 'progress', 'data': interrupt_payload}, ensure_ascii=False)}\n\n"
                return

            filled_pdf_url = result.get("filled_pdf_url")
            full_response = result.get("final_response", "") or "Hoàn tất xử lý biểu mẫu."
            self._save_message(
                session_id=data.idchatsession,
                content=full_response,
                isfromuser=False,
                msgtype="text",
                metadata={"filled_pdf_url": filled_pdf_url} if filled_pdf_url else None,
            )
            self._set_session_status(data.idchatsession, "DONE")

            yield f"data: {json.dumps({'type': 'result', 'message': full_response, 'data': {'filled_pdf_url': filled_pdf_url} if filled_pdf_url else None}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            self._set_session_status(data.idchatsession, "FAILED")
            if not graph_task.done():
                graph_task.cancel()
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

    async def submit_dynamic_form_stream(self, data: DynamicFormSubmitRequest):
        latest_form_message = self._get_latest_dynamic_form_message(data.idchatsession)
        latest_meta = latest_form_message.meta_data if latest_form_message else None

        if latest_meta and latest_meta.get("request_id") and latest_meta.get("request_id") != data.request_id:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Biểu mẫu đã hết hiệu lực, vui lòng gửi lại yêu cầu mới.'}, ensure_ascii=False)}\n\n"
            return

        self._set_session_status(data.idchatsession, "RUNNING")
        self._build_config(data.idchatsession)

        queue = asyncio.Queue()
        set_queue(queue)

        graph_task = asyncio.create_task(self.app.ainvoke(Command(resume=data.values), self.config))

        try:
            async for chunk in self._stream_queue_events(queue, graph_task):
                yield chunk

            result = await graph_task
            interrupt_payload = self._extract_interrupt_payload(result)
            if interrupt_payload:
                self._save_message(
                    session_id=data.idchatsession,
                    content="Cần thêm dữ liệu để tiếp tục.",
                    isfromuser=False,
                    msgtype="dynamic_form",
                    metadata=interrupt_payload,
                )
                self._set_session_status(data.idchatsession, "WAITING_FORM_INPUT")
                yield f"data: {json.dumps({'type': 'progress', 'data': interrupt_payload}, ensure_ascii=False)}\n\n"
                return

            filled_pdf_url = result.get("filled_pdf_url")
            full_response = result.get("final_response", "") or "Hoàn tất xử lý biểu mẫu."
            self._save_message(
                session_id=data.idchatsession,
                content=full_response,
                isfromuser=False,
                msgtype="text",
                metadata={"filled_pdf_url": filled_pdf_url} if filled_pdf_url else None,
            )
            self._set_session_status(data.idchatsession, "DONE")

            yield f"data: {json.dumps({'type': 'result', 'node': 'forms', 'message': full_response, 'data': {'filled_pdf_url': filled_pdf_url} if filled_pdf_url else None}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            self._set_session_status(data.idchatsession, "FAILED")
            if not graph_task.done():
                graph_task.cancel()
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
