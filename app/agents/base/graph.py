from app.agents.base.state import AgentState
from langgraph.graph import StateGraph, END, START
from app.agents.supervisor.supervisor_agent import supervisor_node
from app.agents.qa.qa_agent import qa_node


workflow = StateGraph(AgentState)

workflow.add_node("supervisor", supervisor_node)
workflow.add_node("qa", qa_node)

workflow.set_entry_point("supervisor")

app = workflow.compile()

# print(app.get_graph().draw_ascii())

