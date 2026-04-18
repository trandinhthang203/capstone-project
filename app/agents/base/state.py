from typing import TypedDict, Annotated, Optional
from langgraph.graph.message import add_messages
from dataclasses import dataclass
from typing import List, Union

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

class AgentState(TypedDict):
    user_input: str
    messages: Annotated[list, add_messages]
    session_id: str
    user_id: str

    procedures: list[str]  
    resolved_procedures: list[ProcedureMatch]           
    pipeline: list[str]    
    fields: list[str]      
    current_agent: str          
    next_agent: str             

    qa_output: Optional[QAOutput]
    forms_output: Optional[FormsOutput]
    location_output: Optional[LocationOutput]

    error: Optional[str]
    final_response: Optional[str]