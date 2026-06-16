import os

from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage

from app.core.config import supervisor_prompt
from app.helpers.utils.common import invoke_llm_text, safe_json_loads

CHAT_MEMORY_RECENT_MESSAGES = int(os.getenv("CHAT_MEMORY_RECENT_MESSAGES", "8"))
CHAT_MEMORY_SUMMARY_TRIGGER_MESSAGES = int(os.getenv("CHAT_MEMORY_SUMMARY_TRIGGER_MESSAGES", "12"))
CHAT_MEMORY_SUMMARY_REFRESH_INTERVAL = int(os.getenv("CHAT_MEMORY_SUMMARY_REFRESH_INTERVAL", "4"))


def _role_of(msg: BaseMessage) -> str:
    role = getattr(msg, "type", "") or msg.__class__.__name__.lower()
    if role in {"human", "user"}:
        return "user"
    if role in {"ai", "assistant"}:
        return "assistant"
    return role


def format_messages_for_prompt(messages: list[BaseMessage], max_messages: int | None = None) -> str:
    slice_messages = messages[-max_messages:] if max_messages else messages
    lines: list[str] = []
    for msg in slice_messages:
        content = getattr(msg, "content", "")
        if isinstance(content, list):
            content = " ".join(str(x) for x in content)
        lines.append(f"{_role_of(msg)}: {str(content).strip()}")
    return "\n".join(lines).strip()


async def maybe_refresh_summary(existing_summary: str, messages: list[BaseMessage]) -> str:
    if len(messages) <= CHAT_MEMORY_SUMMARY_TRIGGER_MESSAGES:
        return existing_summary or ""

    if len(messages) % CHAT_MEMORY_SUMMARY_REFRESH_INTERVAL != 0 and existing_summary:
        return existing_summary

    older_messages = messages[:-CHAT_MEMORY_RECENT_MESSAGES]
    if not older_messages:
        return existing_summary or ""

    transcript = format_messages_for_prompt(older_messages)

    prompt = supervisor_prompt["CONVERSATION_SUMMARY_PROMPT"].format(
        existing_summary=existing_summary or "Chưa có tóm tắt trước đó.",
        transcript=transcript,
    )

    summary = await invoke_llm_text([HumanMessage(content=prompt)])
    return summary.strip()


async def resolve_followup(
    raw_query: str,
    messages: list[BaseMessage],
    summary: str,
    last_domain: str | None,
    last_procedures: list[str],
    last_answer: str,
) -> dict:
    if len(messages) < 2 and not summary and not last_domain and not last_procedures:
        return {
            "is_followup": False,
            "standalone_query": raw_query,
            "should_inherit_domain": False,
            "should_inherit_procedures": False,
            "confidence": 0.0,
            "reason": "Không có ngữ cảnh trước đó.",
        }

    prior_messages = messages[:-1] if messages else []
    recent_messages = format_messages_for_prompt(
        prior_messages,
        max_messages=CHAT_MEMORY_RECENT_MESSAGES,
    )

    prompt = supervisor_prompt["FOLLOWUP_RESOLUTION_PROMPT"].format(
        raw_query=raw_query,
        summary=summary or "Chưa có tóm tắt",
        recent_messages=recent_messages or "Không có",
        last_domain=last_domain or "null",
        last_procedures=", ".join(last_procedures) if last_procedures else "[]",
        last_answer=last_answer or "Chưa có câu trả lời trước đó",
    )

    return safe_json_loads(
        await invoke_llm_text([HumanMessage(content=prompt)]),
        fallback={
            "is_followup": False,
            "standalone_query": raw_query,
            "should_inherit_domain": False,
            "should_inherit_procedures": False,
            "confidence": 0.0,
            "reason": "Fallback parser.",
        },
    )
