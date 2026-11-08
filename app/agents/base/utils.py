import contextvars
from typing import Any

from app.agents.base.state import StreamEvent

_queue: contextvars.ContextVar[Any | None] = contextvars.ContextVar("workflow_queue", default=None)

def set_queue(queue: Any) -> contextvars.Token:
    return _queue.set(queue)

def reset_queue(token: contextvars.Token) -> None:
    _queue.reset(token)

async def emit(event: StreamEvent) -> None:
    queue = _queue.get()
    if queue is not None:
        await queue.put(event)
