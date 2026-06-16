import asyncio
import json
import os
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

_llm = ChatGoogleGenerativeAI(
    model=os.getenv("LLM_MODEL", "gemini-2.5-flash"),
    google_api_key=GEMINI_API_KEY,
    temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
    max_tokens=None,
    timeout=LLM_TIMEOUT_SECONDS,
    max_retries=int(os.getenv("LLM_MAX_RETRIES", "5")),
)


def _normalize_llm_text(content: Any) -> str:
    if content is None:
        return ""

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item.strip())
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                chunks.append(item["text"].strip())
            elif hasattr(item, "text") and isinstance(item.text, str):
                chunks.append(item.text.strip())
        return "\n".join([c for c in chunks if c]).strip()

    return str(content).strip()


def window_messages(messages: list[AnyMessage], max_messages: int | None = None) -> list[AnyMessage]:
    limit = max_messages or LLM_MAX_CONTEXT_MESSAGES
    if limit <= 0:
        return list(messages)
    return list(messages[-limit:])


def build_llm_messages(
    prompt: str,
    messages: list[AnyMessage],
    summary: str = "",
    max_messages: int | None = None,
    extra_system_context: str = "",
) -> list[AnyMessage]:
    system_blocks = [prompt.strip()]

    if summary:
        system_blocks.append(
            "## Tóm tắt hội thoại trước đó\n"
            f"{summary.strip()}"
        )

    if extra_system_context:
        system_blocks.append(
            "## Ngữ cảnh bổ sung\n"
            f"{extra_system_context.strip()}"
        )

    return [
        SystemMessage(content="\n\n".join(system_blocks)),
        *window_messages(messages, max_messages=max_messages),
    ]


async def invoke_llm_text(messages: list[AnyMessage]) -> str:
    response = await asyncio.to_thread(_llm.invoke, messages)
    return _normalize_llm_text(response.content)


async def get_response_llm(
    prompt: str,
    messages: list[AnyMessage],
    summary: str = "",
    max_messages: int | None = None,
    extra_system_context: str = "",
) -> str:
    llm_messages = build_llm_messages(
        prompt=prompt,
        messages=messages,
        summary=summary,
        max_messages=max_messages,
        extra_system_context=extra_system_context,
    )
    return await invoke_llm_text(llm_messages)


def safe_json_loads(raw: Any, fallback: dict | None = None) -> dict:
    fallback = fallback or {}
    text = _normalize_llm_text(raw)
    text = text.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(text)
    except Exception:
        return fallback


def read_yaml():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "config.yaml")

    with open(config_path, "r", encoding="utf-8") as f:
        content = yaml.safe_load(f)
        return ConfigBox(content)


def read_json(base_url, file_name):
    file_path = os.path.join(base_url, file_name)
    with open(file_path, "r", encoding="utf-8") as file:
        data = json.load(file)
        return data
