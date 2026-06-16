from app.agents.base.state import AgentState, SupervisorOutput, QAOutput, StreamEvent
from langgraph.types import Command
from langgraph.graph import END
from typing import Literal
from app.agents.base.utils import get_next_agent, format_context, emit, extract_forms_url, _default_reply
from app.helpers.utils.common import get_response_llm
from app.core.config import supervisor_prompt
from app.db.session import get_db
from sqlalchemy import text
from app.helpers.utils.logger import logging
from app.helpers.utils.exception import CustomException
from app.agents.qa.qa_tools import build_query_plan, build_where_clause, TABLE_ALIASES
from langchain.messages import AIMessage
from langsmith import traceable
from app.agents.supervisor.constants import NO_PROCEDURE_ANSWERS
import random

@traceable
async def qa_node(state: AgentState) -> Command[Literal["forms", "location", "__end__"]]:
    intent = state.get("intent", "chitchat")

    if intent in ("chitchat", "unclear"):
        await emit(StreamEvent(
            type="progress",
            node="qa",
            message="Đang xử lý câu hỏi..."
        ))
        
        await emit(StreamEvent(
            type="result", 
            node="qa",
            message=_default_reply(intent)
        ))
        
        return Command(
            goto=END,
            update={"final_response": _default_reply(intent)},
        )


    current_agent = "qa"
    pipeline = state["pipeline"]
    next_agent = get_next_agent(pipeline, current_agent) 
    messages = state["messages"]
    user_input = state.get("resolved_user_input") or state["user_input"]
    logging.info(f"[qa_node] user_input: {user_input}")

    procedure_ids = state["procedures"]

    await emit(StreamEvent(
        type="progress", 
        node="qa",
        message="Đang tìm thông tin cho thủ tục..."
    ))

    if not procedure_ids:
        answer = random.choice(NO_PROCEDURE_ANSWERS)

        await emit(StreamEvent(
            type="result", 
            node="qa",
            message=answer
        ))

        return Command(
            goto=next_agent,
            update={
                "final_response": answer,
                "messages": [AIMessage(content=answer)],
                "last_answer": answer,
                "last_domain": state.get("domain"),
                "last_procedures": procedure_ids,
            }
        )


    try:
        case = SupervisorOutput(
            procedures=procedure_ids,
            fields=state.get("fields", []),
        )
        sql_query = build_query_plan(case).main_sql
        _, main_params = build_where_clause(case.procedures, TABLE_ALIASES["thu_tuc"])
        logging.info(f"[qa_node] Generated SQL: {sql_query}")
    except CustomException as e:
        logging.error(f"[qa_node] Failed to build SQL: {e}")
        raise  

    try:
        with next(get_db()) as db:
            result = db.execute(text(sql_query), main_params)
            rows = result.fetchall()
            columns = list(result.keys())
        logging.info(f"[qa_node] Rows returned: {len(rows)}")
    except Exception as e:
        logging.error(f"[qa_node] DB execution error: {e}", exc_info=True)
        raise 

    context = format_context(rows, columns)
    pdf_urls = extract_forms_url(rows, columns)

    existing_pdf_urls: list[dict] = state.get("pdf_urls") or []
    existing_keys = {item["loai_giay_to"] for item in existing_pdf_urls}
    merged_pdf_urls = existing_pdf_urls + [
        item for item in pdf_urls
        if item["loai_giay_to"] not in existing_keys
    ]
    
    await emit(StreamEvent(
        type="progress", 
        node="qa",
        message="Đang tổng hợp câu trả lời..."
    ))

    answer_prompt = supervisor_prompt["ANSWER_GENERATION"].format(
        query=user_input,
        context=context,
        pipeline=pipeline
    )

    answer = await get_response_llm(
        prompt=answer_prompt,
        messages=messages,
        summary=state.get("conversation_summary", ""),
        max_messages=6,
    )

    logging.info(f"[qa_node] Next agent: {next_agent}")

    await emit(StreamEvent(
        type="result", 
        node="qa",
        message=answer,
        data={"answer": answer},
    ))

    return Command(
        goto=next_agent,
        update={
            "final_response": answer,
            "messages": [AIMessage(content=answer)],
            "pdf_urls": merged_pdf_urls,
            "last_answer": answer,
            "last_domain": state.get("domain"),
            "last_procedures": procedure_ids,
        }
    )