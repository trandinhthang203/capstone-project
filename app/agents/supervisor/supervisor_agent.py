from app.agents.base.state import AgentState
from langgraph.types import Command
from typing import Literal
from app.helpers.utils.common import get_response_llm
from app.core.config import *
import json
from app.helpers.utils.logger import logging
from app.helpers.utils.common import read_json
from langsmith import traceable
from langchain.messages import HumanMessage, AIMessage
from langgraph.graph import END

@traceable
def supervisor_node(state: AgentState) -> Command[Literal["qa", "__end__"]]:
    messages = state["messages"]
    user_input = messages[-1].content

    prompt = supervisor_prompt["SUPERVISOR_PROMPT_V2"].format(
        query = user_input
    )

    response = get_response_llm(prompt, messages)
    data = json.loads(response)

    procedures = data.get("procedures", [])
    logging.info(f"[supervisor_node] procedures original: {procedures}")
    if not procedures:
        return Command(
            goto=END,
            update={
                "messages": [AIMessage(content=json.dumps(data, ensure_ascii=False))],
            },
    )

    name_ids = read_json("app/agents/supervisor", "name_id.json")

    procedure_ids = [name_ids[proc] for proc in procedures if proc in name_ids]    

    return Command(
        goto=data["pipeline"][0],
        update={
            "procedures": procedure_ids,
            "messages": [AIMessage(content=json.dumps(data, ensure_ascii=False))],
            "pipeline": data.get("pipeline", ["qa"]),
            "fields": data.get("fields", [])
        },
    )


    

