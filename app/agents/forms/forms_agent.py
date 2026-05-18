from app.agents.forms.forms_tools import *
from app.agents.base.state import AgentState
from app.helpers.utils.common import _llm
from langsmith import traceable

TOOLS = [select_form_url, load_pdf_from_url, extract_form_fields, fill_form_fields, preview_filled_form]
llm_with_tools = _llm.bind_tools(TOOLS)  

SYSTEM_PROMPT = """Bạn là Forms Agent – trợ lý điền mẫu đơn hành chính tự động.

## Quy trình bắt buộc
1. Gọi `select_form_url` với `pdf_urls` lấy từ state và yêu cầu người dùng.
   - Nếu status="found"     → dùng selected_url, chuyển bước 2.
   - Nếu status="ambiguous" → hiển thị danh sách candidates, hỏi người dùng chọn số thứ tự,
                               sau khi người dùng chọn → dùng URL tương ứng, chuyển bước 2.
   - Nếu status="not_found" → thông báo không tìm thấy, yêu cầu cung cấp link trực tiếp.
2. Gọi `load_pdf_from_url` với pdf_url đã xác định.
3. Gọi `extract_form_fields` với pdf_path vừa nhận.
4. Hiển thị danh sách trường rõ ràng cho người dùng.
5. Yêu cầu người dùng cung cấp các trường thông tin đó.
6. Gọi `fill_form_fields` khi đủ thông tin.
7. Gọi `preview_filled_form` rồi hỏi người dùng muốn chỉnh sửa không.
8. Lặp 5-7 đến khi người dùng xác nhận hoàn tất.

Trình bày tên trường bằng tiếng Việt tự nhiên.
"""


@traceable
async def forms_node(state: AgentState) -> dict:
    msgs = list(state["messages"])

    if not any(isinstance(m, SystemMessage) for m in msgs):
        pdf_urls = state.get("pdf_urls", [])
        system_with_context = (
            SYSTEM_PROMPT
            + f"\n\n## Danh sách biểu mẫu hiện có (pdf_urls)\n"
            + json.dumps(pdf_urls, ensure_ascii=False, indent=2)
        )
        msgs = [SystemMessage(content=system_with_context), *msgs]

    return {"messages": [llm_with_tools.invoke(msgs)]}
