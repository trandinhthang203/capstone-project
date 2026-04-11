from app.agents.base.state import AgentState, FormsOutput, LocationOutput, QAOutput
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

def qa_node(state: AgentState) -> dict:
    user_input = state["user_input"]
    procedures = state["procedures"]

    # sql_prompt = supervisor_prompt["SQL_GENERATION"].format(
    #     procedure_names=procedures,
    #     query=user_input
    # )
    try:
        # raw_sql = get_response_llm(sql_prompt, user_input)
        # sql_query = validate_sql(raw_sql)
        sql_query = f"SELECT * FROM rag.thu_tuc t WHERE t.ten_thu_tuc ILIKE '%{procedures[0]}%'"
        logging.info(f"[qa_node] Generated SQL: {sql_query}")
    except CustomException as e:
        logging.warning(f"[qa_node] Invalid SQL: {e}")

    try:
        with next(get_db()) as db:
            results = db.execute(text(sql_query))
            rows = results.fetchall()
            columns = list(results.keys())
        logging.info(f"[qa_node] Rows returned: {len(rows)}")
    except Exception as e:
        logging.error(f"[qa_node] DB execution error: {e}", exc_info=True)

    context = format_context(rows, columns)
    answer_prompt = supervisor_prompt["ANSWER_GENERATION"].format(
        query=user_input,
        context=context,
        link=None
    )

    answer = get_response_llm(answer_prompt, user_input)

    return {
        "final_response" : answer
    }

