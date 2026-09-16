from typing import TypedDict, Annotated, Optional, Any

from langgraph.graph.message import add_messages


class FormsState(TypedDict, total=False):
    # shared input from parent graph
    user_input: str
    resolved_user_input: str
    messages: Annotated[list, add_messages]
    user_id: str
    procedures: list[str]
    pdf_urls: list

    # forms-only internal state
    pdf_url_selected: Optional[str]
    form_name_selected: Optional[str]
    forms_fill_mode: Optional[str]
    forms_mode_choice_payload: Optional[dict[str, Any]]
    pdf_local_path: Optional[str]
    extracted_form_fields: list[dict[str, Any]]
    dynamic_form_payload: Optional[dict[str, Any]]
    submitted_form_values: Optional[dict[str, Any]]

    # shared output back to parent graph
    final_response: Optional[str]
    filled_pdf_url: Optional[str]
