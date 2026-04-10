from app.agents.base.state import AgentState, FormsOutput, LocationOutput, QAOutput
from langgraph.types import Command
from typing import Literal
from app.agents.base.utils import get_next_agent
from app.helpers.utils.common import get_response_llm
from app.core.config import *
import json

def supervisor_node(state: AgentState) -> Command[Literal["qa"]]:
    user_input = state['user_input']
    prompt = supervisor_prompt["SUPERVISOR_PROMPT"].format(
        query = user_input
    )
    response = get_response_llm(prompt, user_input)
    print(response)
    data = json.loads(response)
    print(data)

    return Command(
        goto = data["pipeline"][0],
        update={
            "procedures" : data["procedures"],
            "pipeline" : data["pipeline"]
        }
    )

# def test_supervisor():
#     # Tạo state giả
#     state = AgentState(
#         user_input="Điền giúp tôi mẫu đơn này",
#         messages=[],
#         session_id="test-001",
#         procedures=[],
#         pipeline=[],
#         current_agent="",
#         next_agent="",
#         qa_output=None,
#         forms_output=None,
#         location_output=None,
#         error=None,
#         final_response=None,
#     )

#     result = supervisor_node(state)
#     print("goto     :", result.goto)
#     print("pipeline :", result.update["pipeline"])
#     print("procedures:", result.update["procedures"])

# test_supervisor()




    

