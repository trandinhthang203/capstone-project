# app/agents/workflow.py
from langgraph.graph import StateGraph, END, START
from app.agents.base.state import AgentState
from app.agents.supervisor.supervisor_agent import supervisor_node
from app.agents.qa.qa_agent import qa_node
from app.agents.memory.checkpointer import get_checkpointer
from app.agents.memory.store import get_store

def create_workflow():                                  
    checkpointer = get_checkpointer()
    store = get_store()

    workflow = StateGraph(AgentState)
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("qa", qa_node)
    workflow.set_entry_point("supervisor")
    workflow.add_edge("qa", END)

    return workflow.compile(
        checkpointer=checkpointer,
        store=store,
    )
app = create_workflow()