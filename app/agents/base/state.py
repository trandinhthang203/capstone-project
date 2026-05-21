from typing import TypedDict, Annotated, Optional
from langgraph.graph.message import add_messages
from dataclasses import dataclass
import operator
from pydantic import BaseModel
from typing import Literal, Any
from datetime import datetime

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
    # type: str = ""
    node: str = ""
    message: str                   
    data: Any = None               
    timestamp: datetime = datetime.now()     

class AgentState(TypedDict, total=False):
    user_input: str
    messages: Annotated[list, add_messages]
    session_id: str
    user_id: str
    summary: str

    procedures: list[str]
    resolved_procedures: list
    pipeline: list[str]
    fields: list[str]
    current_agent: str
    next_agent: str
    context: str
    node_outputs: str

    pdf_urls: list
    pdf_local_path: str
    filled_pdf_path: str
    final_response: Optional[str]

    # NEW
    extracted_form_fields: list[dict[str, Any]]
    dynamic_form_payload: Optional[dict[str, Any]]
    submitted_form_values: Optional[dict[str, Any]]