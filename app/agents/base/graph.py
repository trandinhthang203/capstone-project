from langgraph.graph import END, StateGraph

from app.agents.base.state import AgentState
from app.agents.forms.forms_agent import forms_node, forms_wait_input_node, forms_fill_node
from app.agents.location.location_agent import location_node
from app.agents.memory.checkpointer import get_checkpointer
from app.agents.memory.store import get_store
from app.agents.qa.qa_node import qa_node
from app.agents.supervisor.supervisor_node import context_node, intent_node, supervisor_node


async def create_workflow():
    checkpointer = await get_checkpointer()
    store = await get_store()

    workflow = StateGraph(AgentState)
    workflow.add_node("context", context_node)
    workflow.add_node("intent", intent_node)
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("qa", qa_node)

    workflow.add_node("forms", forms_node)
    workflow.add_node("forms_wait_input", forms_wait_input_node)
    workflow.add_node("forms_fill", forms_fill_node)

    workflow.add_node("location", location_node)
    workflow.set_entry_point("context")

    return workflow.compile(checkpointer=checkpointer, store=store)
