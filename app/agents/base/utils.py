from langgraph.graph import END
import json
import asyncio
from contextvars import ContextVar
from app.agents.base.state import StreamEvent

ALLOWED_SQL_STATEMENTS = ("SELECT",)


_event_queue: ContextVar[asyncio.Queue] = ContextVar("event_queue")

def get_queue() -> asyncio.Queue:
    return _event_queue.get()

def set_queue(q: asyncio.Queue):
    _event_queue.set(q)

async def emit(event: StreamEvent):
    q = get_queue()
    if q:
        await q.put(event)
def get_next_agent(pipeline: list[str], current_agent: str) -> str | list[str]:
    
    try:
        if current_agent not in pipeline:
            return END
        
        for i, step in enumerate(pipeline):
            if step == current_agent:
                return pipeline[i + 1]

    except(Exception) as e:
        return END
    
def format_context(rows, columns) -> str:
    data = [dict(zip(columns, row)) for row in rows]
    return json.dumps(data, ensure_ascii=False, indent=2)

def validate_sql(query: str) -> str:
    query_striped = query.strip().upper()

    if not any(query_striped.startswith(stmt) for stmt in ALLOWED_SQL_STATEMENTS):
        raise ValueError(f"Câu lệnh không được phép: {query[:100]}")
    return query.strip()
