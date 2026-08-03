import asyncio
import json
import random
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END
from langgraph.types import Command
from langsmith import traceable

from app.agents.base.state import AgentState, StreamEvent, SupervisorOutput
from app.agents.base.utils import _default_reply, emit, get_next_agent
from app.agents.supervisor.constants import NO_PROCEDURE_ANSWERS
from app.core.config import supervisor_prompt
from app.helpers.utils.common import _llm, get_response_llm, safe_json_loads
from app.helpers.utils.logger import logging
from app.agents.qa.helper import _build_qa_one_pass_prompt, _compact_payload, QA_DEFAULT_FIELDS, _run_initial_query_async


@traceable
async def qa_node(state: AgentState) -> Command[Literal["forms", "location", "__end__"]]:
    intent = state.get("intent", "chitchat")
    user_input = state.get("resolved_user_input") or state["user_input"]
    procedure_ids = state.get("procedures", []) or []
    procedure_names = state.get("procedure_names", []) or []
    pipeline = state.get("pipeline", []) or []
    next_agent = get_next_agent(pipeline, "qa")

    # Short-circuit chitchat/unclear
    if intent in ("chitchat", "unclear"):
        reply = _default_reply(intent)
        await emit(StreamEvent(type="result", node="qa", message=reply))
        return Command(
            goto=END,
            update={"final_response": reply, "messages": [AIMessage(content=reply)]},
        )

    # Short-circuit không match procedure 
    if not procedure_ids:
        answer = random.choice(NO_PROCEDURE_ANSWERS)
        await emit(StreamEvent(type="result", node="qa", message=answer))
        return Command(
            goto=next_agent,
            update={
                "final_response": answer,
                "messages": [AIMessage(content=answer)],
                "last_answer": answer,
                "last_domain": state.get("domain"),
                "last_procedures": procedure_ids,
            },
        )

    await emit(StreamEvent(type="progress", node="qa", message="Đang truy vấn dữ liệu thủ tục..."))

    fields = state.get("fields") or QA_DEFAULT_FIELDS
    try:
        initial_payload = await _run_initial_query_async(procedure_ids, fields)
    except Exception as exc:
        logging.error("[qa_node] DB error: %s", exc, exc_info=True)
        answer = f"Hiện không thể truy vấn dữ liệu thủ tục. Bạn thử lại sau ít phút nhé."
        return Command(
            goto=END,
            update={"final_response": answer, "messages": [AIMessage(content=answer)]},
        )

    merged_pdf_urls = (state.get("pdf_urls") or []) + (initial_payload.get("pdf_urls") or [])
    seen = set()
    dedup = []
    for item in merged_pdf_urls:
        key = item.get("loai_giay_to")
        if key and key not in seen:
            seen.add(key)
            dedup.append(item)
    merged_pdf_urls = dedup

    compact_ctx = _compact_payload(initial_payload)

    await emit(StreamEvent(type="progress", node="qa", message="Đang tạo câu trả lời..."))

    prompt = _build_qa_one_pass_prompt(
        user_input=user_input,
        procedure_names=procedure_names,
        procedure_ids=procedure_ids,
        context=compact_ctx,
        pipeline=pipeline,
    )

    final_answer = await get_response_llm(
        prompt=prompt,
        messages=state.get("messages", []),
        summary=state.get("conversation_summary", ""),
        max_messages=4,
    )

    await emit(StreamEvent(type="result", node="qa", message=final_answer))

    return Command(
        goto=next_agent,
        update={
            "final_response": final_answer,
            "messages": [AIMessage(content=final_answer)],
            "pdf_urls": merged_pdf_urls,
            "last_answer": final_answer,
            "last_procedures": procedure_ids,
        },
    )
