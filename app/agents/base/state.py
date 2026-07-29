from typing import TypedDict, Annotated, Optional, Any, Literal
from dataclasses import dataclass
from datetime import datetime

from langgraph.graph.message import add_messages
from pydantic import BaseModel


@dataclass
class QAOutput(TypedDict):
    answer_text: str
    form_id: Optional[str]
    office_id: Optional[str]
    requirements: list[str]
    confidence: float


class FormsOutput(TypedDict):
    form_data: dict
    filled_fields: list[str]
    missing_fields: list[str]
    pdf_url: Optional[str]


class LocationOutput(TypedDict):
    office_name: str
    address: str
    maps_url: str
    working_hours: str


class ProcedureMatch(TypedDict):
    ma_thu_tuc: str
    ten_thu_tuc: str
    score: float


@dataclass
class SupervisorOutput:
    procedures: list[str]
    fields: list[str]


class StreamEvent(BaseModel):
    type: Literal["progress", "result", "error"]
    node: str = ""
    message: str
    data: Any = None
    timestamp: datetime = datetime.now()


class AgentState(TypedDict, total=False):
    # input/runtime
    user_input: str
    resolved_user_input: str
    messages: Annotated[list, add_messages]
    session_id: str
    user_id: str

    # conversation memory
    conversation_summary: str
    is_followup: bool
    followup_confidence: float
    followup_reason: str

    # last resolved context
    last_answer: str
    last_domain: Optional[str]
    last_procedures: list[str]
    procedure_names: list[str]

    # classifier / routing
    intent: str
    domain: str
    intent_confidence: float

    procedures: list[str]
    resolved_procedures: list
    pipeline: list[str]
    fields: list[str]
    current_agent: str
    next_agent: str
    context: str
    node_outputs: str

    # Qdrant retrieval cache (dùng nội bộ giữa intent_node → supervisor_node)
    _qdrant_candidates: list[str]

    # outputs
    pdf_urls: list
    pdf_local_path: str
    filled_pdf_path: str
    final_response: Optional[str]
    filled_pdf_url: Optional[str]
    google_docs_url: Optional[str]

    # forms
    pdf_url_selected: Optional[str]
    form_name_selected: Optional[str]
    forms_fill_mode: Optional[str]
    forms_mode_choice_payload: Optional[dict[str, Any]]
    extracted_form_fields: list[dict[str, Any]]
    dynamic_form_payload: Optional[dict[str, Any]]
    dynamic_form_prefill_values: Optional[dict[str, Any]]
    submitted_form_values: Optional[dict[str, Any]]
