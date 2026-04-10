from app.agents.base.state import AgentState, FormsOutput, LocationOutput, QAOutput
from langgraph.types import Command
from typing import Literal
from app.agents.base.utils import get_next_agent, format_context
from app.helpers.utils.common import get_response_llm
from app.core.config import *
import json
from app.db.session import get_db
from sqlalchemy import text

db = next(get_db())

def qa_node(state: AgentState) -> dict:
    user_input = state["user_input"]
    procedures = state["procedures"]

    sql_prompt = supervisor_prompt["SQL_GENERATION"].format(
        procedure_names=procedures,
        query=user_input
    )

    sql_query = get_response_llm(sql_prompt, user_input)
    results = db.execute(text(sql_query))
    rows = results.fetchall()
    columns = results.keys()

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

