import asyncio
import os
from functools import lru_cache

from dotenv import load_dotenv
from mem0 import Memory

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION_MEM0", "chatbot_mem0")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
MEM0_EMBEDDING_DIM = int(os.getenv("MEM0_EMBEDDING_DIM", "384"))

config = {
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "collection_name": QDRANT_COLLECTION,
            "embedding_model_dims": MEM0_EMBEDDING_DIM,
            "url": QDRANT_URL,
            "api_key": QDRANT_API_KEY,
        },
    },
    "embedder": {
        "provider": "huggingface",
        "config": {
            "model": os.getenv(
                "MEM0_EMBEDDING_MODEL",
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            ),
            "embedding_dims": MEM0_EMBEDDING_DIM,
        },
    },
    "llm": {
        "provider": "groq",
        "config": {
            "model": os.getenv("MEM0_LLM_MODEL", "qwen/qwen3.8-27b"),
            "temperature": 0.1,
            "max_tokens": min(int(os.getenv("MEM0_LLM_MAX_TOKENS", "512")), 512),
        },
    },
}

@lru_cache(maxsize=1)
def _client() -> Memory:
    """Khởi tạo Mem0 một lần và giữ nguyên lỗi gốc để dễ chẩn đoán."""
    return Memory.from_config(config)

async def recall(user_id: str, query: str) -> str:
    client = _client()
    if not user_id or not query:
        return ""
    result = await asyncio.to_thread(client.search, query, user_id=user_id, limit=5)
    rows = result.get("results", result) if isinstance(result, dict) else result
    return "\n".join(str(row.get("memory", "")) for row in (rows or []) if isinstance(row, dict))

async def remember(user_id: str, user_text: str, assistant_text: str) -> None:
    client = _client()
    if user_id and user_text and assistant_text:
        messages = [{"role": "user", "content": user_text},
                    {"role": "assistant", "content": assistant_text}]
        await asyncio.to_thread(client.add, messages, user_id=user_id)
