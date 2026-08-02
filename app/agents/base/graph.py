from langgraph.graph import StateGraph

from app.agents.base.state import AgentState
from app.agents.forms.forms_agent import (
    forms_ask_mode_node, forms_extract_node, forms_fill_node,
    forms_google_docs_node, forms_node, forms_route_node, forms_wait_input_node,
)
from app.agents.location.location_agent import location_node
from app.agents.memory.checkpointer import get_checkpointer
from app.agents.memory.store import get_store
from app.agents.qa.qa_node import qa_node
from app.agents.supervisor.supervisor_node import context_node, intent_router_node


async def create_workflow():
    checkpointer = await get_checkpointer()
    store = await get_store()

    workflow = StateGraph(AgentState)

    # Core pipeline (giảm từ 5 entry nodes xuống 3)
    workflow.add_node("context", context_node)
    workflow.add_node("intent_router", intent_router_node)   # ⬅ gộp intent+supervisor
    workflow.add_node("qa", qa_node)

    # Optional branches
    workflow.add_node("forms", forms_node)
    workflow.add_node("forms_ask_mode", forms_ask_mode_node)
    workflow.add_node("forms_route", forms_route_node)
    workflow.add_node("forms_google_docs", forms_google_docs_node)
    workflow.add_node("forms_extract", forms_extract_node)
    workflow.add_node("forms_wait_input", forms_wait_input_node)
    workflow.add_node("forms_fill", forms_fill_node)

    workflow.add_node("location", location_node)
    workflow.set_entry_point("context")

    return workflow.compile(checkpointer=checkpointer, store=store)
