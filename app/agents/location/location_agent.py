"""
location_agent.py
─────────────────
Agent thực sự: LLM tự quyết định gọi tool nào, thứ tự nào.
Sử dụng ChatGroq (LangChain) thay vì Anthropic native API.

Flow:
  1. Build prompt với đủ context (qa answer + user profile)
  2. LLM nhận tools → tự sinh tool_calls (search + geocode song song, rồi directions)
  3. Thực thi tất cả tool_calls song song bằng asyncio.gather
  4. Nếu LLM chưa có đủ data → vòng lặp tiếp (tối đa MAX_ITER lần)
  5. emit StreamEvent → frontend
"""

from app.agents.base.state import AgentState, StreamEvent
from app.agents.base.utils import get_next_agent, emit
from app.helpers.utils.logger import logging
from app.core.config import settings
from langgraph.types import Command
from langchain_core.messages import AIMessage, ToolMessage, SystemMessage, HumanMessage
from langsmith import traceable
from typing import Literal
from urllib.parse import quote
import asyncio
import json

from app.agents.location.location_tools import search_agency_place, geocode_user_address, get_directions
from app.services.user_service import UserService
from app.db.session import get_db

# ── Constants ────────────────────────────────────────────────────────────────
MAX_ITER = 3   # Giới hạn vòng lặp tool-call, tránh loop vô hạn

# ── Tool registry ─────────────────────────────────────────────────────────────
TOOLS = [search_agency_place, geocode_user_address, get_directions]
TOOL_REGISTRY = {t.name: t for t in TOOLS}

# ── LLM với tools đã bind ─────────────────────────────────────────────────────
from app.helpers.utils.common import _llm  

_llm_with_tools = _llm.bind_tools(TOOLS)


# ── Helpers ───────────────────────────────────────────────────────────────────
def build_system_prompt() -> str:
    return """Bạn là agent chuyên tìm địa điểm thực hiện thủ tục hành chính.

Nhiệm vụ: Từ thông tin thủ tục và địa chỉ người dùng, tìm đường đến cơ quan có thẩm quyền.

Quy tắc sử dụng tool:
1. Gọi search_agency_place và geocode_user_address ĐỒNG THỜI (parallel) trong cùng một lượt.
2. Sau khi có tọa độ cả hai → gọi get_directions.
3. Không gọi get_directions trước khi có đủ tọa độ.
4. Nếu search_agency_place trả về lỗi → thử lại với query ngắn gọn hơn.
5. Khi đã có đủ kết quả từ cả 3 tools → trả về kết quả tổng hợp dạng JSON:
{
  "agency_name": "...",
  "agency_address": "...",
  "agency_lat": 0.0,
  "agency_lng": 0.0,
  "user_address": "...",
  "user_lat": 0.0,
  "user_lng": 0.0,
  "distance": "...",
  "duration": "...",
  "polyline": "...",
  "steps": [...],
  "map_url": "https://www.google.com/maps/dir/..."
}"""


def build_user_prompt(qa_answer: str, user_profile: dict) -> str:
    return f"""Thông tin thủ tục từ hệ thống:
{qa_answer}

Thông tin người dùng:
- Địa chỉ: {user_profile.get("address", "")}
- Tỉnh/thành: {user_profile.get("province", "")}

Hãy tìm địa điểm thực hiện thủ tục và tính đường đi cho người dùng."""


async def execute_tool_calls_parallel(tool_calls: list) -> list[dict]:
    """Thực thi tất cả tool calls song song, trả về list dict chứa id và kết quả."""
    async def run_one(tc):
        # LangChain tool_calls format: {"name": ..., "args": ..., "id": ...}
        tool_fn = TOOL_REGISTRY.get(tc["name"])
        if not tool_fn:
            return {
                "id": tc["id"],
                "content": json.dumps({"error": f"Unknown tool: {tc['name']}"}),
            }
        try:
            result = await tool_fn.ainvoke(tc["args"])
            return {"id": tc["id"], "content": json.dumps(result)}
        except Exception as e:
            logging.error(f"[location_agent] Tool '{tc['name']}' error: {e}", exc_info=True)
            return {"id": tc["id"], "content": json.dumps({"error": str(e)})}

    return await asyncio.gather(*[run_one(tc) for tc in tool_calls])


async def invoke_llm_with_tools(messages: list) -> AIMessage:
    """Gọi LLM với tools đã bind, wrap trong asyncio.to_thread vì ChatGroq là sync."""
    return await asyncio.to_thread(
        _llm_with_tools.invoke,
        [SystemMessage(content=build_system_prompt()), *messages],
    )


def build_map_url(user_address: str, agency_address: str) -> str:
    return f"https://www.google.com/maps/dir/{quote(user_address)}/{quote(agency_address)}"


# ── Main Agent Node ───────────────────────────────────────────────────────────
@traceable
async def location_node(state: AgentState) -> Command[Literal["__end__"]]:
    current_agent = "location"
    next_agent = get_next_agent(state["pipeline"], current_agent)

    qa_answer    = state["final_response"]   # output từ qa_node

    with next(get_db()) as db:
        user_profile = UserService.get_profile_for_chatbot(2)

    logging.info(f"[location_agent] Starting. user_province={user_profile.get('province')}")

    await emit(StreamEvent(
        type="progress", node="location",
        message="Đang xác định địa điểm thực hiện thủ tục..."
    ))

    # ── Agentic loop ──────────────────────────────────────────────────────────
    messages = [HumanMessage(content=build_user_prompt(qa_answer, user_profile))]
    final_result = None

    for iteration in range(MAX_ITER):
        logging.info(f"[location_agent] Iteration {iteration + 1}/{MAX_ITER}")

        response: AIMessage = await invoke_llm_with_tools(messages)
        messages.append(response)

        # ── Kiểm tra có tool_calls không ─────────────────────────────────────
        # LangChain: response.tool_calls là list[dict] hoặc []
        tool_calls = response.tool_calls or []

        if not tool_calls:
            # LLM đã có đủ data, không gọi tool nữa → parse JSON từ content
            try:
                final_result = json.loads(response.content)
                logging.info(f"[location_agent] Got final result on iteration {iteration + 1}")
            except (json.JSONDecodeError, TypeError):
                logging.warning(
                    f"[location_agent] LLM returned non-JSON text: "
                    f"{str(response.content)[:200]}"
                )
            break

        # ── Thực thi tool calls song song ────────────────────────────────────
        logging.info(
            f"[location_agent] Executing tools parallel: "
            f"{[tc['name'] for tc in tool_calls]}"
        )

        tool_results = await execute_tool_calls_parallel(tool_calls)

        # Append ToolMessage vào history để LLM đọc ở vòng tiếp theo
        # LangChain yêu cầu ToolMessage với tool_call_id tương ứng
        messages.extend([
            ToolMessage(
                content=r["content"],
                tool_call_id=r["id"],
            )
            for r in tool_results
        ])

    # ── Fallback nếu loop kết thúc mà không có kết quả ───────────────────────
    if not final_result:
        logging.error("[location_agent] Failed to get final result after max iterations")
        final_result = {
            "error": "Không thể xác định địa điểm",
            "map_url": build_map_url(
                user_profile.get("address", ""),
                f"cơ quan hành chính {user_profile.get('province', '')}",
            ),
        }
    else:
        # Đảm bảo map_url luôn có
        if "map_url" not in final_result:
            final_result["map_url"] = build_map_url(
                final_result.get("user_address", user_profile.get("address", "")),
                final_result.get("agency_address", ""),
            )

    # ── Emit kết quả ─────────────────────────────────────────────────────────
    await emit(StreamEvent(
        type="result",
        node="location",
        message=(
            f"Địa điểm: {final_result.get('agency_name', 'N/A')} — "
            f"Khoảng cách: {final_result.get('distance', 'N/A')}, "
            f"Thời gian: {final_result.get('duration', 'N/A')}"
        ),
        data={"location": final_result},
    ))

    summary = (
        f"Địa điểm thực hiện: {final_result.get('agency_name')}, "
        f"{final_result.get('agency_address')}. "
        f"Từ địa chỉ của bạn khoảng {final_result.get('distance')}, "
        f"mất khoảng {final_result.get('duration')}."
    )

    return Command(
        goto=next_agent,
        update={
            "location_result": final_result,
            "messages": [AIMessage(content=summary)],
        },
    )