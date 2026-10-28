from langgraph.graph import StateGraph, END

from app.agents.base.state import AgentState
from app.agents.forms.graph import build_forms_subgraph
from app.agents.location.location_agent import location_node
from app.agents.memory.checkpointer import get_checkpointer
from app.agents.memory.store import get_store
from app.agents.qa.qa_node import qa_node
from app.agents.supervisor.supervisor_node import context_node, intent_router_node


async def create_workflow():
    checkpointer = await get_checkpointer()
    store = await get_store()

    workflow = StateGraph(AgentState)

    forms_subgraph = build_forms_subgraph()

    # Core pipeline
    workflow.add_node("context", context_node)
    workflow.add_node("intent_router", intent_router_node)
    workflow.add_node("qa", qa_node)

    # Optional branches
    workflow.add_node("forms", forms_subgraph)
    workflow.add_node("location", location_node)

    workflow.set_entry_point("context")

    # forms subgraph return dict -> cần edge tĩnh ra END
    workflow.add_edge("forms", END)

    return workflow.compile(checkpointer=checkpointer, store=store)
