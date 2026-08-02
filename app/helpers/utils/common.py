import asyncio
import os
from functools import lru_cache
from typing import Any

import yaml
from box import ConfigBox
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AnyMessage, SystemMessage

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
LLM_MAX_CONTEXT_MESSAGES = int(os.getenv("LLM_MAX_CONTEXT_MESSAGES", "8"))


@lru_cache(maxsize=1)
def _create_llm():
    """Singleton LLM instance — không tạo mới mỗi request."""
    return ChatGoogleGenerativeAI(
        model=os.getenv("LLM_MODEL", "gemini-2.5-flash"),
        google_api_key=GEMINI_API_KEY,
        temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
        max_tokens=None,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),     # ↓ từ 5 → 3
    )


# ↓ Backward-compat với `from app.helpers.utils.common import _llm`
_llm = _create_llm()


def _normalize_llm_text(content: Any) -> str:
    if content is None: return ""
    if isinstance(content, str): return content.strip()
    if isinstance(content, list):
        chunks = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item.strip())
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                chunks.append(item["text"].strip())
            elif hasattr(item, "text") and isinstance(item.text, str):
                chunks.append(item.text.strip())
        return "\n".join([c for c in chunks if c]).strip()
    return str(content).strip()


def window_messages(messages, max_messages=None):
    limit = max_messages or LLM_MAX_CONTEXT_MESSAGES
    if limit <= 0: return list(messages)
    return list(messages[-limit:])


def build_llm_messages(prompt, messages, summary="", max_messages=None, extra_system_context=""):
    blocks = [prompt.strip()]
    if summary:
        blocks.append("## Tóm tắt hội thoại trước đó\n" + summary.strip())
    if extra_system_context:
        blocks.append("## Ngữ cảnh bổ sung\n" + extra_system_context.strip())
    return [SystemMessage(content="\n\n".join(blocks)), *window_messages(messages, max_messages)]


async def invoke_llm_text(messages):
    response = await asyncio.to_thread(_create_llm().invoke, messages)
    return _normalize_llm_text(response.content)


async def invoke_llm_stream(messages):
    """Streaming variant cho tương lai — emit token đầu tiên ra UI."""
    llm = _create_llm()
    async for chunk in llm.astream(messages):
        text = _normalize_llm_text(chunk.content)
        if text:
            yield text


async def get_response_llm(prompt, messages, summary="", max_messages=None, extra_system_context=""):
    llm_messages = build_llm_messages(prompt=prompt, messages=messages, summary=summary,
                                       max_messages=max_messages,
                                       extra_system_context=extra_system_context)
    return await invoke_llm_text(llm_messages)


def safe_json_loads(raw, fallback=None):
    fallback = fallback or {}
    text = _normalize_llm_text(raw)
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads_safe(text)  # Will fallback if fail
    except Exception:
        try:
            import json
            return json.loads(text)
        except Exception:
            return fallback


def read_yaml():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(base_dir, "config.yaml"), "r", encoding="utf-8") as f:
        return ConfigBox(yaml.safe_load(f))


def read_json(base_url, file_name):
    file_path = os.path.join(base_url, file_name)
    with open(file_path, "r", encoding="utf-8") as file:
        return json_safe_load(file.read())


# Helpers
def json_safe_load(s):
    import json
    return json.loads(s)
