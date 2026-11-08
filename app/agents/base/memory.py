import asyncio
import os
from functools import lru_cache
from typing import Any

@lru_cache(maxsize=1)
def _client() -> Any | None:
    if os.getenv("MEM0_ENABLED", "false").lower() != "true":
        return None
    try:
        from mem0 import Memory
        return Memory.from_config({})
    except (ImportError, RuntimeError, ValueError):
        return None

async def recall(user_id: str, query: str) -> str:
    client = _client()
    if client is None or not user_id or not query:
        return ""
    result = await asyncio.to_thread(client.search, query, user_id=user_id, limit=5)
    rows = result.get("results", result) if isinstance(result, dict) else result
    return "\n".join(str(row.get("memory", "")) for row in (rows or []) if isinstance(row, dict))

async def remember(user_id: str, user_text: str, assistant_text: str) -> None:
    client = _client()
    if client is not None and user_id and user_text and assistant_text:
        messages = [{"role": "user", "content": user_text},
                    {"role": "assistant", "content": assistant_text}]
        await asyncio.to_thread(client.add, messages, user_id=user_id)
