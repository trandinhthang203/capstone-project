from app.agents.base.state import AgentState
from langgraph.types import Command
from typing import Literal
from app.helpers.utils.common import get_response_llm
from app.core.config import *
import json
from app.helpers.utils.logger import logging
from app.helpers.utils.common import read_json

def supervisor_node(state: AgentState) -> Command[Literal["qa"]]:
    user_input = state['user_input']
    prompt = supervisor_prompt["SUPERVISOR_PROMPT_V2"].format(
        query = user_input
    )
    response = get_response_llm(prompt, user_input)
    data = json.loads(response)

    # resolved = []
    procedures = data.get("procedures", [])
    logging.info(f"[supervisor_node] procedures original: {procedures}")

    name_ids = read_json("app/agents/supervisor", "name_id.json")

    procedure_ids = [name_ids[proc] for proc in procedures if proc in name_ids]    
    # if procedures:
    #     db = next(get_db())
    #     try:
    #         resolved = resolve_procedures_fts(
    #             db=db,
    #             user_query=user_input,
    #             supervisor_candidates=procedures,
    #         )
    #     finally:
    #         db.close()

    #     if resolved:
    #         data["procedures"] = [item["ten_thu_tuc"] for item in resolved]

    # logging.info(f"[supervisor_node]: {resolved}")

    return Command(
        goto=data["pipeline"][0],
        update={
            "procedures": procedure_ids,
            # "resolved_procedures": resolved,
            "pipeline": data.get("pipeline", ["qa"]),
            "fields": data.get("fields", [])
        },
    )



###################################### WHY  INCREASE LATENCY ~ 30S ALTHOUGH ONLY HAVE 2 REQUEST ###########################


    

