import json
import uuid

from langsmith import traceable
from langgraph.types import interrupt
from langchain_core.messages import SystemMessage, ToolMessage, AIMessage

from app.agents.forms.forms_tools import (
    select_form_url,
    load_pdf_from_url,
    extract_form_fields,
    fill_form_fields,
    preview_filled_form,
)
from app.agents.base.state import AgentState, StreamEvent
from app.agents.base.utils import emit
from app.helpers.utils.common import _llm
from app.agents.forms.helper import _is_last_message_from_tool, _find_last_tool_payload, _build_dynamic_form_payload

TOOLS = [select_form_url, load_pdf_from_url, extract_form_fields, fill_form_fields, preview_filled_form]
llm_with_tools = _llm.bind_tools(TOOLS)

SYSTEM_PROMPT = """Bạn là Forms Agent – trợ lý điền mẫu đơn hành chính tự động.

## Quy trình bắt buộc
1. Gọi `select_form_url` với `pdf_urls` lấy từ state và yêu cầu người dùng.
2. Gọi `load_pdf_from_url` với pdf_url đã xác định.
3. Gọi `extract_form_fields` với pdf_path vừa nhận.
4. Khi đã có danh sách field, KHÔNG hỏi người dùng bằng văn bản tự do.
   Hệ thống sẽ tạm dừng để UI hiển thị form động.
5. Sau khi hệ thống nhận dữ liệu từ UI, tiếp tục điền form bằng `fill_form_fields`.
6. Gọi `preview_filled_form`.
7. Trả về kết quả hoàn tất.
"""

@traceable
async def forms_node(state: AgentState) -> dict:
    msgs = list(state["messages"])

    if not any(isinstance(m, SystemMessage) for m in msgs):
        pdf_urls = state.get("pdf_urls", [])
        system_with_context = (
            SYSTEM_PROMPT
            + "\n\n## Danh sách biểu mẫu hiện có (pdf_urls)\n"
            + json.dumps(pdf_urls, ensure_ascii=False, indent=2)
        )
        msgs = [SystemMessage(content=system_with_context), *msgs]

    # 1) Nếu tool extract_form_fields vừa chạy xong -> interrupt để UI render form động
    if _is_last_message_from_tool(msgs, "extract_form_fields"):
        extract_payload = _find_last_tool_payload(msgs, "extract_form_fields") or {}
        load_payload = _find_last_tool_payload(msgs, "load_pdf_from_url") or {}

        fields = extract_payload.get("fields", [])
        pdf_path = load_payload.get("pdf_path")

        form_payload = _build_dynamic_form_payload(fields, pdf_path)

        await emit(StreamEvent(
            type="progress",
            node="forms",
            message="Đã trích xuất xong các trường, đang chờ người dùng nhập form..."
        ))

        submitted_values = interrupt(form_payload)

        field_values = {}
        for f in fields:
            value = submitted_values.get(f["field_id"])
            if value is not None and str(value).strip():
                field_values[f["field_id"]] = {
                    "value": str(value).strip(),
                    "x": f["x"],
                    "y": f["y"],
                }

        filled_raw = await fill_form_fields.ainvoke({
            "pdf_path": pdf_path,
            "field_values": field_values
        })
        filled_payload = json.loads(filled_raw)

        preview_raw = await preview_filled_form.ainvoke({
            "pdf_path": filled_payload["output_path"]
        })
        preview_payload = json.loads(preview_raw)

        await emit(StreamEvent(
            type="result",
            node="forms",
            message="Đã điền xong biểu mẫu.",
            data={
                "filled_pdf": filled_payload,
                "preview": preview_payload
            }
        ))

        return {
            "submitted_form_values": submitted_values,
            "filled_pdf_path": filled_payload["output_path"],
            "dynamic_form_payload": None,
            "final_response": "Tôi đã điền xong biểu mẫu và tạo preview cho bạn.",
            "messages": [
                AIMessage(content="Tôi đã nhận dữ liệu từ form động và hoàn tất việc điền biểu mẫu.")
            ],
        }

    # 2) Chưa tới bước interrupt thì vẫn chạy như cũ
    return {"messages": [llm_with_tools.invoke(msgs)]}
