from app.agents.base.state import AgentState, SupervisorOutput
from langgraph.types import Command
from typing import Literal
from app.agents.base.utils import get_next_agent, format_context, validate_sql
from app.helpers.utils.common import get_response_llm
from app.core.config import *
import json
from app.db.session import get_db
from sqlalchemy import text
from app.helpers.utils.logger import logging
from app.helpers.utils.exception import CustomException
from app.agents.qa.qa_tools import build_query_plan, build_where_clause, TABLE_ALIASES
from langsmith import traceable
from typing import Literal
from app.agents.base.utils import emit
from app.agents.base.state import StreamEvent
from langchain.messages import AIMessage

@traceable
async def qa_node(state: AgentState) -> Command[Literal["forms", "location", "__end__"]]:
    current_agent = "qa"
    pipeline = state["pipeline"]
    next_agent = get_next_agent(pipeline, current_agent),

    messages = state["messages"]
    user_input = state["user_input"]
    logging.info(f"[qa_node]: user_input: {user_input}")

    procedure_ids = state["procedures"]
    # logging.info(f"[qa_node]: procedure_ids: {procedure_ids}")

    await emit(StreamEvent(
        type="progress", node="qa",
        message="Đang tìm thông tin cho thủ tục..."
    ))

    try:
        case = SupervisorOutput(
            procedures = procedure_ids,
            fields = state.get("fields", []),
        )

        sql_query = build_query_plan(case).main_sql
        _, main_params = build_where_clause(case.procedures, TABLE_ALIASES["thu_tuc"])
        logging.info(f"[qa_node] Generated SQL: {sql_query}")
    except CustomException as e:
        logging.warning(f"[qa_node] Invalid SQL: {e}")

    try:
        with next(get_db()) as db:
            results = db.execute(text(sql_query), main_params)
            rows = results.fetchall()
            columns = list(results.keys())
        logging.info(f"[qa_node] Rows returned: {len(rows)}")
    except Exception as e:
        logging.error(f"[qa_node] DB execution error: {e}", exc_info=True)

    context = format_context(rows, columns)
    await emit(StreamEvent(
        type="progress", node="qa",
        message="Đang tổng hợp câu trả lời..."
    ))
    answer_prompt = supervisor_prompt["ANSWER_GENERATION"].format(
        query=user_input,
        context=context,
        link=None
    )

    answer = await get_response_llm(answer_prompt, messages)
    logging.info(f"[qa_node] Answer returned: {answer}")

    await emit(StreamEvent(
        type="result", node="qa",
        message=f"Đã tìm thấy thông tin: {answer}",
        data={"answer": answer}
    ))

    return Command(
        goto=get_next_agent(pipeline, current_agent),
        update={
            "final_response" : answer,
            "messages": [AIMessage(content=answer)]
        }
    )
