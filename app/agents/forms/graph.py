from langgraph.graph import StateGraph, END

from app.agents.forms.state import FormsState
from app.agents.forms.forms_agent import (
    forms_node,
    forms_ask_mode_node,
    forms_route_node,
    forms_google_docs_node,
    forms_extract_node,
    forms_wait_input_node,
    forms_fill_node,
)


def build_forms_subgraph():
    workflow = StateGraph(FormsState)

    workflow.add_node("select_form", forms_node)
    workflow.add_node("forms_ask_mode", forms_ask_mode_node)
    workflow.add_node("forms_route", forms_route_node)
    workflow.add_node("forms_google_docs", forms_google_docs_node)
    workflow.add_node("forms_extract", forms_extract_node)
    workflow.add_node("forms_wait_input", forms_wait_input_node)
    workflow.add_node("forms_fill", forms_fill_node)

    workflow.set_entry_point("select_form")

    # Các node return dict cần edge ra END
    workflow.add_edge("forms_google_docs", END)
    workflow.add_edge("forms_fill", END)

    return workflow.compile()
