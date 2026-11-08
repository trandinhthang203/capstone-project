import os
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agents.base.nodes import (ask_clarify, context_builder, direct_reply,
    history_summary, legal_retrieval, procedure_retrieval, understand_query)
from app.agents.base.state import AgentState

def route_query(state: AgentState) -> str | list[Send]:
    if state.get("needs_clarification") and state.get("clarification_count", 0) < 2:
        return "ask_clarify"
    intent = state.get("intent")
    if intent in {"chitchat", "out_of_scope"}:
        return "direct_reply"
    if intent == "both":
        return [Send("procedure_retrieval", state), Send("legal_retrieval", state)]
    return "legal_retrieval" if intent == "legal" else "procedure_retrieval"

async def _checkpointer() -> Any:
    url = os.getenv("LANGGRAPH_CHECKPOINT_DATABASE_URL")
    if not url:
        return MemorySaver()
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    saver = AsyncPostgresSaver.from_conn_string(url)
    if hasattr(saver, "__aenter__"):
        saver = await saver.__aenter__()
    await saver.setup()
    return saver

async def create_workflow(checkpointer: Any | None = None):
    graph = StateGraph(AgentState)
    for name, node in (("history_summary", history_summary), ("understand_query", understand_query),
                       ("direct_reply", direct_reply), ("ask_clarify", ask_clarify),
                       ("procedure_retrieval", procedure_retrieval), ("legal_retrieval", legal_retrieval),
                       ("context_builder", context_builder)):
        graph.add_node(name, node)
    graph.add_edge(START, "history_summary")
    graph.add_edge("history_summary", "understand_query")
    graph.add_conditional_edges("understand_query", route_query,
        ["direct_reply", "ask_clarify", "procedure_retrieval", "legal_retrieval"])
    graph.add_edge("ask_clarify", "understand_query")
    graph.add_edge("direct_reply", END)
    graph.add_edge("procedure_retrieval", "context_builder")
    graph.add_edge("legal_retrieval", "context_builder")
    graph.add_edge("context_builder", END)
    return graph.compile(checkpointer=checkpointer or await _checkpointer())
