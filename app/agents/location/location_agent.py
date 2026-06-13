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
from app.agents.supervisor.helper import _parse_location_response
from app.agents.location.location_tools import search_agency_place, get_directions
from app.services.user_service import UserService
from app.db.session import get_db
from app.helpers.utils.common import _llm  
import random

MAX_ITER = 5
TOOLS = [search_agency_place, get_directions]
TOOL_REGISTRY = {t.name: t for t in TOOLS}

_llm_with_tools = _llm.bind_tools(TOOLS)


def build_system_prompt() -> str:
    return """Bạn là agent chuyên tìm địa điểm thực hiện thủ tục hành chính.

Nhiệm vụ: Từ thông tin thủ tục và địa chỉ người dùng, tìm đường đến cơ quan có thẩm quyền.

Quy tắc sử dụng tool:
1. Gọi search_agency_place để lấy địa chỉ cơ quan.
2. Sau khi có địa chỉ cơ quan → gọi get_directions với địa chỉ người dùng và địa chỉ cơ quan.
3. Không gọi get_directions trước khi có địa chỉ cơ quan từ search_agency_place.
4. Nếu search_agency_place trả về lỗi → thử lại với query ngắn gọn hơn.
5. Khi đã có đủ kết quả từ get_directions → trả về JSON theo đúng format sau, không giải thích, không thêm bất kỳ text nào ngoài JSON:
{
  "start_address": "...",
  "end_address": "...",
  "directions_message": "Đoạn hướng dẫn đường đi dựa vào kết quả get_directions"
}"""


def build_user_prompt(qa_answer: str, user_profile: dict) -> str:
    return f"""Thông tin thủ tục từ hệ thống:
{qa_answer}

Thông tin người dùng:
- Địa chỉ: {user_profile.get("address", "")}
- Tỉnh/thành: {user_profile.get("province", "")}
- Quận: {user_profile.get("district", "")}
- Đường: {user_profile.get("ward", "")}

Hãy tìm địa điểm thực hiện thủ tục và tính đường đi cho người dùng."""


async def execute_tool_calls_parallel(tool_calls: list) -> list[dict]:
    """Thực thi tất cả tool calls song song, trả về list dict chứa id và kết quả."""
    async def run_one(tc):
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
    """Gọi LLM với retry khi gặp rate limit (429)."""
    for attempt in range(MAX_ITER):
        try:
            return await asyncio.to_thread(
                _llm_with_tools.invoke,
                [SystemMessage(content=build_system_prompt()), *messages],
            )
        except Exception as e:
            is_rate_limit = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)

            if is_rate_limit and attempt < MAX_ITER - 1:
                wait = (2 ** attempt) + random.uniform(0, 1)  
                logging.warning(
                    f"[location_agent] Rate limit hit (attempt {attempt + 1}/{MAX_ITER}), "
                    f"retrying in {wait:.1f}s..."
                )
                await asyncio.sleep(wait)
            else:
                raise


@traceable
async def location_node(state: AgentState) -> Command[Literal["__end__"]]:
    current_agent = "location"
    next_agent = get_next_agent(state["pipeline"], current_agent)

    qa_answer = state["final_response"]   
    user_id   = state["user_id"]  
    logging.info(f"[location_agent] User id: {user_id}")

    with next(get_db()) as db:
        user_service = UserService(db)
        user_profile = user_service.get_profile_for_chatbot(user_id)

    logging.info(f"[location_agent] Starting. user_province={user_profile.get('province')}")

    await emit(StreamEvent(
        type="progress", 
        node="location",
        message="Đang xác định địa điểm thực hiện thủ tục..."
    ))

    messages = [HumanMessage(content=build_user_prompt(qa_answer, user_profile))]
    final_result = None

    for iteration in range(MAX_ITER):
        logging.info(f"[location_agent] Iteration {iteration + 1}/{MAX_ITER}")

        response = await invoke_llm_with_tools(messages)
        logging.info(f"[location_agent] Response location {response}")

        messages.append(response)
        content_response = response.content
        tool_calls = response.tool_calls or []

        if not tool_calls:
            try:
                final_result = _parse_location_response(content_response["text"])
                logging.info(f"[location_agent] Got final result on iteration {iteration + 1}")
            except (json.JSONDecodeError, TypeError):
                logging.warning(
                    f"[location_agent] LLM returned non-JSON text: "
                    f"{str(response.content)[:200]}"
                )
            break

        logging.info(
            f"[location_agent] Executing tools parallel: "
            f"{[tc['name'] for tc in tool_calls]}"
        )

        tool_results = await execute_tool_calls_parallel(tool_calls)
        messages.extend([
            ToolMessage(content=r["content"], tool_call_id=r["id"])
            for r in tool_results
        ])

    if not final_result:
        logging.error("[location_agent] Failed to get final result after max iterations")
        final_result = {
            "error": "Không thể xác định địa điểm",
            "directions_message": "Không thể xác định địa điểm thực hiện thủ tục.",
            "start_address": user_profile.get("address", ""),
            "end_address": "",
        }

    summary = final_result.get("directions_message", "Không thể tạo hướng dẫn đường đi.")

    await emit(StreamEvent(
        type="result",
        node="location",
        message=summary,
        data={
            "location": {
                **final_result,
                "origin": final_result.get("start_address", ""),
                "destination": final_result.get("end_address", ""),
            }
        },
    ))

    return Command(
        goto=next_agent,
        update={
            "final_response": summary,
            "messages": [AIMessage(content=summary)],
        },
    )