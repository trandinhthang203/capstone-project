from app.agents.base.state import AgentState, FormsOutput, LocationOutput, QAOutput
from langgraph.types import Command
from typing import Literal
from app.agents.base.utils import get_next_agent
from app.helpers.utils.common import get_response_llm
from app.core.config import *
import json
from app.db.session import get_db
from app.agents.supervisor.supervisor_tools import resolve_procedures_fts
from app.helpers.utils.logger import logging

def supervisor_node(state: AgentState) -> Command[Literal["qa"]]:
    user_input = state['user_input']
    prompt = supervisor_prompt["SUPERVISOR_PROMPT_V2"].format(
        query = user_input
    )
    response = get_response_llm(prompt, user_input)
    data = json.loads(response)

    resolved = []
    procedures = data.get("procedures", [])
    logging.info(f"[supervisor_node] procedures original: {procedures}")

    if procedures:
        db = next(get_db())
        try:
            resolved = resolve_procedures_fts(
                db=db,
                user_query=user_input,
                supervisor_candidates=procedures,
            )
        finally:
            db.close()

        if resolved:
            data["procedures"] = [item["ten_thu_tuc"] for item in resolved]

    logging.info(f"[supervisor_node]: {resolved}")

    return Command(
        goto=data["pipeline"][0],
        update={
            "procedures": data.get("procedures", []),
            "resolved_procedures": resolved,
            "pipeline": data.get("pipeline", ["qa"]),
            "fields": data.get("fields", [])
        },
    )




    

