import os

from langchain_core.messages import BaseMessage, HumanMessage

from app.core.config import supervisor_prompt
from app.helpers.utils.common import invoke_llm_text, safe_json_loads

CHAT_MEMORY_RECENT_MESSAGES = int(os.getenv("CHAT_MEMORY_RECENT_MESSAGES", "8"))
CHAT_MEMORY_SUMMARY_TRIGGER_MESSAGES = int(os.getenv("CHAT_MEMORY_SUMMARY_TRIGGER_MESSAGES", "20"))
CHAT_MEMORY_SUMMARY_REFRESH_INTERVAL = int(os.getenv("CHAT_MEMORY_SUMMARY_REFRESH_INTERVAL", "8"))


def _role_of(msg):
    role = getattr(msg, "type", "") or msg.__class__.__name__.lower()
    if role in {"human", "user"}: return "user"
    if role in {"ai", "assistant"}: return "assistant"
    return role


def format_messages_for_prompt(messages, max_messages=None):
    slice_messages = messages[-max_messages:] if max_messages else messages
    lines = []
    for msg in slice_messages:
        content = getattr(msg, "content", "")
        if isinstance(content, list):
            content = " ".join(str(x) for x in content)
        lines.append(f"{_role_of(msg)}: {str(content).strip()}")
    return "\n".join(lines).strip()

async def maybe_refresh_summary(existing_summary, messages, summarized_upto=0):
    if len(messages) <= CHAT_MEMORY_SUMMARY_TRIGGER_MESSAGES:
        return existing_summary or "", summarized_upto

    if len(messages) % CHAT_MEMORY_SUMMARY_REFRESH_INTERVAL != 0 and existing_summary:
        return existing_summary, summarized_upto

    # Chỉ lấy phần MỚI: từ chỗ đã tóm tắt trước đó → tới trước k message gần nhất
    cutoff = len(messages) - CHAT_MEMORY_RECENT_MESSAGES
    new_older = messages[summarized_upto:cutoff]

    if not new_older:
        return existing_summary or "", summarized_upto

    transcript = format_messages_for_prompt(new_older)  # chỉ phần mới, không phải cả trăm msg
    prompt = supervisor_prompt["CONVERSATION_SUMMARY_PROMPT"].format(
        existing_summary=existing_summary or "Chưa có tóm tắt trước đó.",
        transcript=transcript,
    )

    import asyncio
    summary = await asyncio.to_thread(lambda: _sync_invoke(prompt))
    return summary.strip(), cutoff  # trả thêm watermark mới để lưu lại


def _sync_invoke(prompt):
    import asyncio
    return asyncio.run(invoke_llm_text([HumanMessage(content=prompt)]))


async def resolve_followup(raw_query, messages, summary, last_procedures, last_answer):
    if len(messages) < 2 and not summary and not last_procedures:
        return {
            "is_followup": False, 
            "standalone_query": raw_query,
            "confidence": 0.0, 
            "reason": "No prior context",
        }
    prior = messages[:-1] if messages else []
    recent = format_messages_for_prompt(prior, max_messages=CHAT_MEMORY_RECENT_MESSAGES)
    prompt = supervisor_prompt["FOLLOWUP_RESOLUTION_PROMPT"].format(
        raw_query=raw_query, 
        summary=summary or "Chưa có tóm tắt",
        recent_messages=recent or "Không có",
        last_procedures=", ".join(last_procedures) if last_procedures else "[]",
        last_answer=last_answer or "Chưa có câu trả lời trước đó",
    )
    raw_text = await invoke_llm_text([HumanMessage(content=prompt)])
    parsed = safe_json_loads(raw_text, fallback={
        "is_followup": False, 
        "standalone_query": raw_query,
        "confidence": 0.0, 
        "reason": "fallback",
    })
    return parsed
