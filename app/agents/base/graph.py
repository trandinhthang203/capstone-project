# graph.py
from langgraph.graph import StateGraph, END
from app.agents.base.state import AgentState
from app.agents.supervisor.supervisor_node import supervisor_node
from app.agents.qa.qa_node import qa_node
from app.agents.memory.checkpointer import get_checkpointer
from app.agents.memory.store import get_store
from app.agents.forms.forms_agent import forms_node, TOOLS
from app.agents.location.location_agent import location_node
from langgraph.prebuilt import ToolNode
from langchain_core.messages import AIMessage

def should_continue(state: AgentState) -> str:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
        return "tools"
    return END

async def create_workflow():
    checkpointer = await get_checkpointer()
    store = await get_store()

    workflow = StateGraph(AgentState)
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("qa", qa_node)
    workflow.add_node("forms", forms_node)
    workflow.add_node("tools", ToolNode(TOOLS))
    workflow.add_node("location", location_node)
    workflow.add_conditional_edges("forms", should_continue, {"tools": "tools", END: END})
    workflow.add_edge("tools", "forms")
    workflow.set_entry_point("supervisor")
    workflow.add_edge("qa", END)

    return workflow.compile(checkpointer=checkpointer, store=store)