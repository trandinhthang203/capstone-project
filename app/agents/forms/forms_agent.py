from app.agents.forms.forms_tools import *
from app.agents.base.state import AgentState
from app.helpers.utils.common import _llm
from langsmith import traceable

async def forms_node(state: AgentState):
    pass

TOOLS = [select_form_url, load_pdf_from_url, extract_form_fields, fill_form_fields, preview_filled_form]
llm_with_tools = _llm.bind_tools(TOOLS)  

SYSTEM_PROMPT = """Bạn là Forms Agent – trợ lý điền mẫu đơn hành chính tự động.

## Quy trình bắt buộc
1. Gọi `load_pdf_from_url` với pdf_url được cung cấp.
2. Gọi `extract_form_fields` với pdf_path vừa nhận.
3. Hiển thị danh sách trường rõ ràng cho người dùng.
4. Yêu cầu người dùng cung cấp các trường thông tin đó.
5. Gọi `fill_form_fields` khi đủ thông tin.
6. Gọi `preview_filled_form` rồi hỏi người dùng muốn chỉnh sửa không.
7. Lặp 4-6 đến khi người dùng cung cấp đủ các trường cần thiết.

Trình bày tên trường bằng tiếng Việt tự nhiên.
"""


@traceable
async def forms_node(state: AgentState) -> dict:
    msgs = list(state["messages"])
    if not any(isinstance(m, SystemMessage) for m in msgs):
        msgs = [SystemMessage(content=SYSTEM_PROMPT), *msgs]
    return {"messages": [llm_with_tools.invoke(msgs)]}

@traceable
async def should_continue(state: AgentState) -> str:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
        return "tools"
    return END
