import contextvars
from typing import Any

from app.agents.base.state import StreamEvent, AgentState
import unicodedata
import time
_queue: contextvars.ContextVar[Any | None] = contextvars.ContextVar("workflow_queue", default=None)

def set_queue(queue: Any) -> contextvars.Token:
    return _queue.set(queue)

def reset_queue(token: contextvars.Token) -> None:
    _queue.reset(token)

async def emit(event: StreamEvent) -> None:
    queue = _queue.get()
    if queue is not None:
        await queue.put(event)


def _text(message: Any) -> str:
    return str(getattr(message, "content", message))


def _normalize_procedure_text(value: str) -> str:
    """Normalize Vietnamese procedure text for conservative identity checks."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return " ".join("".join(
        char if char.isalnum() else " " for char in without_marks
    ).split())


def _timed(name: str, started: float, state: AgentState) -> dict[str, float]:
    timings = dict(state.get("node_timings_ms", {}))
    timings[name] = round((time.perf_counter() - started) * 1000, 2)
    return timings

