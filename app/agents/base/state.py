from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

Intent = Literal["chitchat", "out_of_scope", "procedure", "legal", "both"]


class ProcedureFilters(TypedDict, total=False):
    code: str
    name: str
    issuing_agency: str
    implementing_agency: str
    domain: str
    status: str


def merge_dicts(left: dict, right: dict) -> dict:
    return {**left, **right}


class QueryUnderstanding(BaseModel):
    intent: Intent
    rewritten_query: str
    procedure_name: str | None = Field(
        default=None,
        description="Tên thủ tục hành chính dùng để tìm kiếm; không chứa phần câu hỏi chi tiết.",
    )


class AgentState(TypedDict, total=False):
    # init state in mesage service
    messages: Annotated[list[AnyMessage], add_messages]
    user_id: str
    session_id: str
    user_input: str
    user_role: str

    history_summary: str
    long_term_memory: str
    summarized_message_count: int

    rewritten_query: str
    intent: Intent
    needs_clarification: bool
    clarification_question: str
    clarification_count: int
    procedure_name: str
    procedure_filters: ProcedureFilters
    procedure_candidates: list[dict[str, Any]]
    selected_procedure_code: str
    selected_procedure_name: str
    procedure_results: list[dict[str, Any]]
    legal_results: list[dict[str, Any]]
    context_sufficient: bool
    missing_information: str
    final_answer: str
    node_timings_ms: Annotated[dict[str, float], merge_dicts]


@dataclass(slots=True)
class StreamEvent:
    type: Literal["progress", "result", "error"]
    node: str = ""
    message: str = ""
    data: Any = None
