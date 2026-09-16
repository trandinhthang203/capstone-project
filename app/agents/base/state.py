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
    user_id: str

    # conversation memory
    conversation_summary: str
    summarized_upto: int

    # previous turn context
    last_answer: str
    procedure_names: list[str]

    # routing / supervisor -> qa
    intent: str
    procedures: list[str]
    pipeline: list[str]
    fields: list[str]

    # shared data between qa -> forms
    pdf_urls: list

    # final outputs
    final_response: Optional[str]
    filled_pdf_url: Optional[str]

    # optional: nếu bạn muốn typing sạch với supervisor/qa hiện tại
    domain: Optional[str]
