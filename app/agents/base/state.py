from typing import TypedDict, Annotated, Optional
from langgraph.graph.message import add_messages


class QAOutput(TypedDict):
    answer_text: str
    form_id: Optional[str]        # Forms Agent sẽ đọc field này
    office_id: Optional[str]      # Location Agent sẽ đọc field này
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


class AgentState(TypedDict):
    user_input: str
    messages: Annotated[list, add_messages]
    session_id: str

    procedures: list[str]  
    resolved_procedures: list[ProcedureMatch]            # ["cấp lại CCCD", "đăng ký kinh doanh"]
    pipeline: list[str]           # ["qa", "forms", "location"]
    current_agent: str            # "supervisor"
    next_agent: str               # "qa"

    # Mỗi agent điền vào field của mình
    qa_output: Optional[QAOutput]
    forms_output: Optional[FormsOutput]
    location_output: Optional[LocationOutput]

    # Control flow
    error: Optional[str]
    final_response: Optional[str]