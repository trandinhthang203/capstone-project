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
        
def get_next_agent(pipeline: list[str], current_agent: str):
    if current_agent not in pipeline:
        return END
    
    idx = pipeline.index(current_agent)
    
    if idx == len(pipeline) - 1:
        return END
    
    return pipeline[idx + 1]
    
def format_context(rows, columns) -> str:
    data = [dict(zip(columns, row)) for row in rows]
    return json.dumps(data, ensure_ascii=False, indent=2)

def validate_sql(query: str) -> str:
    query_striped = query.strip().upper()

    if not any(query_striped.startswith(stmt) for stmt in ALLOWED_SQL_STATEMENTS):
        raise ValueError(f"Câu lệnh không được phép: {query[:100]}")
    return query.strip()


def extract_forms_url(rows, columns) -> list[dict]:
    """
    Trích xuất thông tin biểu mẫu từ kết quả truy vấn.
    Chỉ lấy các trường 'loai_giay_to' và 'mau_don_to_khai'.
    Loại bỏ các dòng không có 'loai_giay_to'.
    """
    data = [dict(zip(columns, row)) for row in rows]
    
    forms = []
    seen = set()
    
    for item in data:
        loai_giay_to = item.get("loai_giay_to") or ""
        mau_don_to_khai = item.get("mau_don_to_khai") or ""
        
        if not loai_giay_to:
            continue
        
        # Dedup theo loai_giay_to
        if loai_giay_to in seen:
            continue
        seen.add(loai_giay_to)
        
        forms.append({
            "loai_giay_to": loai_giay_to,
            "mau_don_to_khai": mau_don_to_khai,
        })
    
    return forms

def _default_reply(intent: str) -> str:
    if intent == "unclear":
        return (
            "Tôi chưa hiểu rõ câu hỏi của bạn. "
            "Bạn có thể mô tả cụ thể hơn về thủ tục hoặc giấy tờ bạn cần hỗ trợ không?"
        )
    return (
        "Xin chào! Tôi chuyên hỗ trợ các thủ tục hành chính. "
        "Bạn cần tư vấn về lĩnh vực nào?"
    )