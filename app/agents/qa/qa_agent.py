from app.agents.base.state import AgentState, FormsOutput, LocationOutput, QAOutput, SupervisorOutput
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

def qa_node(state: AgentState) -> dict:
    user_input = state["user_input"]
    # procedures = state["procedures"]
    resolved = state.get("resolved_procedures", [])

    procedure_ids = [p["ma_thu_tuc"] for p in resolved]
    logging.info(f"[qa_node]: procedure_ids: {procedure_ids}")
    # procedure_names = [p["ten_thu_tuc"] for p in resolved]

    # sql_prompt = supervisor_prompt["SQL_GENERATION"].format(
    #     procedure_ids=procedure_ids,
    #     procedure_names=procedure_names,
    #     query=user_input
    # )
    # sql_prompt = supervisor_prompt["SQL_GENERATION"].format(
    #     procedure_names=procedures,
    #     query=user_input
    # )
    try:
        # raw_sql = get_response_llm(sql_prompt, user_input)
        # sql_query = validate_sql(raw_sql)
        # sql_query = f"SELECT * FROM rag.thu_tuc t WHERE t.ma_thu_tuc = ANY(ARRAY[{procedure_ids}])"
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
            # results = db.execute(text(sql_query))
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

