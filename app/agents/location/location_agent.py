import asyncio
import json
import random
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.types import Command
from langsmith import traceable

from app.agents.base.state import AgentState, StreamEvent
from app.agents.base.utils import emit, get_next_agent
from app.agents.location.location_tools import get_directions, search_agency_place
from app.agents.supervisor.helper import _parse_location_response
from app.db.session import get_db
from app.helpers.utils.common import _llm
from app.helpers.utils.logger import logging
from app.services.user_service import UserService

MAX_ITER = 5
TOOLS = [search_agency_place, get_directions]
TOOL_REGISTRY = {t.name: t for t in TOOLS}
_llm_with_tools = _llm.bind_tools(TOOLS)

def build_system_prompt() -> str:
    return """Bạn là agent chuyên tìm địa điểm thực hiện thủ tục hành chính.

Nhiệm vụ:
1. Xác định cơ quan tiếp nhận hồ sơ phù hợp từ thông tin thủ tục.
2. Tìm địa chỉ cơ quan bằng search_agency_place.
3. Sau khi có địa chỉ cơ quan, dùng get_directions để tính đường đi từ địa chỉ người dùng.

Quy tắc bắt buộc:
- Khi gọi search_agency_place, tham số `query` PHẢI là tên cơ quan ghép với tên xã/phường, quận/huyện hoặc tỉnh/thành
  của người dùng. Không dùng tên cơ quan chung chung như "Ủy ban nhân dân cấp quận" mà phải là "Ủy ban nhân dân quận Liên Chiểu, Đà Nẵng".
- Không gọi get_directions nếu chưa có địa chỉ cơ quan rõ ràng.
- Nếu thiếu địa chỉ người dùng hoặc không tính được đường đi, vẫn phải trả về JSON hợp lệ và nêu rõ lỗi ngắn gọn.
- Chỉ trả về JSON, không thêm giải thích bên ngoài JSON.

Cách tạo directions_message từ kết quả get_directions:
- Dùng các trường: html_instructions, distance.text, duration.text
- Viết thành đoạn văn hướng dẫn tự nhiên bằng tiếng Việt, liệt kê tuần tự các bước rẽ/đi thẳng
- Kết thúc bằng tổng quãng đường và thời gian ước tính
- Định dạng directions_message theo mẫu sau (dùng \\n để xuống dòng):
  Ví dụ: "Từ [start_address] → [end_address]\\n\\nĐầu tiên: [html_instructions bước 1] ([distance bước 1])\\nTiếp theo: [html_instructions bước 2] ([distance bước 2])\\nSau đó: [html_instructions bước 3] ([distance bước 3])\\n...\\nĐến nơi ở bên phải.\\n\\n Tổng quãng đường: 3.8km\\n Thời gian ước tính: 6 phút 40 giây"
- Bỏ qua bước "arrive" (maneuver = arrive) khi liệt kê, chỉ dùng để kết thúc câu "đến nơi"
- Nếu get_directions không trả về kết quả hợp lệ, ghi rõ lý do vào trường error và để directions_message rỗng

JSON output:
{
  "start_address": "", -> Địa chỉ của người dùng
  "end_address": "",  -> Thông tin cơ quan trả về từ search_agency_place
  "distance": "",
  "duration": "",
  "directions_message": "",
  "error": ""
}"""

def _compose_user_address(user_profile: dict[str, Any]) -> str:
    ordered_parts: list[str] = []
    for key in ("address", "ward", "district", "province"):
        value = (user_profile.get(key) or "").strip()
        if value and value not in ordered_parts:
            ordered_parts.append(value)
    return ", ".join(ordered_parts)


def build_user_prompt(qa_answer: str, user_profile: dict[str, Any]) -> str:
    full_address = _compose_user_address(user_profile)
    province = user_profile.get("province", "")
    district = user_profile.get("district", "")
    ward = user_profile.get("ward", "")

    return f"""Thông tin thủ tục từ hệ thống QA:
{qa_answer}

Thông tin người dùng:
- Địa chỉ đầy đủ: {full_address}
- Tỉnh/thành: {province}
- Quận/huyện: {district}
- Phường/xã: {ward}

Yêu cầu:
- Xác định tên cơ quan tiếp nhận hồ sơ từ thông tin thủ tục (ví dụ: "Ủy ban nhân dân cấp quận", "Chi cục Thuế", ...).
- Khi gọi search_agency_place, tham số `query` phải ghép tên cơ quan với địa bàn cụ thể của người dùng.
  Ví dụ: nếu cơ quan là "Ủy ban nhân dân cấp quận" và người dùng ở quận "{district}", tỉnh "{province}"
  thì query = "Ủy ban nhân dân {district}, {province}"
  Ví dụ khác: "Chi cục Thuế {district}, {province}" hoặc "Phòng Tư pháp {district}, {province}"
- Truyền province="{province}", district="{district}", ward="{ward}" vào search_agency_place để tăng độ chính xác.
- Sau khi có địa chỉ cơ quan, gọi get_directions để tính đường đi từ địa chỉ người dùng.
"""


def _extract_text_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text.strip()
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
        if chunks:
            return "\n".join(chunks).strip()
        return json.dumps(content, ensure_ascii=False)
    return str(content).strip()


def _json_dumps(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


def _build_direction_summary(route: dict, agency_name: str = "") -> str:
    start_address = route.get("start_address", "")
    end_address = route.get("end_address", "")
    distance = route.get("distance", "")
    duration = route.get("duration", "")
    steps = route.get("steps") or []

    header = f"Từ {start_address} đến {end_address}"
    if agency_name:
        header += f" ({agency_name})"

    summary_parts = [header]
    if distance or duration:
        summary_parts.append(f"quãng đường khoảng {distance}, thời gian di chuyển khoảng {duration}.")

    if steps:
        top_steps = [step.get("instruction", "") for step in steps[:3] if step.get("instruction")]
        if top_steps:
            summary_parts.append("Các bước chính: " + " → ".join(top_steps))

    return " ".join(part for part in summary_parts if part).strip()


def _build_fallback_result(
    user_profile: dict[str, Any],
    reason: str,
    agency_name: str = "",
    end_address: str = "",
    route: dict | None = None,
) -> dict:
    route = route or {}
    start_address = route.get("start_address") or _compose_user_address(user_profile)
    end_address = route.get("end_address") or end_address
    directions_message = route.get("directions_message") or reason

    if route and not route.get("directions_message") and (route.get("distance") or route.get("duration")):
        directions_message = _build_direction_summary(route, agency_name=agency_name)

    return {
        "agency_name": agency_name,
        "start_address": start_address,
        "end_address": end_address,
        "distance": route.get("distance", ""),
        "duration": route.get("duration", ""),
        "directions_message": directions_message,
        "error": reason if reason else route.get("error", ""),
    }


async def _run_tool_call(tc: dict, args: dict | None = None) -> dict:
    tool_fn = TOOL_REGISTRY.get(tc["name"])
    if not tool_fn:
        return {
            "id": tc["id"],
            "name": tc["name"],
            "args": args or tc.get("args", {}),
            "payload": {"error": f"Unknown tool: {tc['name']}"},
            "content": _json_dumps({"error": f"Unknown tool: {tc['name']}"}),
        }

    final_args = args or tc.get("args", {})
    try:
        result = await tool_fn.ainvoke(final_args)
        return {
            "id": tc["id"],
            "name": tc["name"],
            "args": final_args,
            "payload": result,
            "content": _json_dumps(result),
        }
    except Exception as exc:
        logging.error(f"[location_agent] Tool '{tc['name']}' error: {exc}", exc_info=True)
        error_payload = {"error": str(exc)}
        return {
            "id": tc["id"],
            "name": tc["name"],
            "args": final_args,
            "payload": error_payload,
            "content": _json_dumps(error_payload),
        }


async def execute_tool_calls(tool_calls: list[dict], user_profile: dict[str, Any]) -> list[dict]:
    """
    Luôn xử lý search_agency_place trước, sau đó mới patch args cho get_directions.
    Điều này giúp location agent bền hơn khi LLM gọi tool chưa đúng thứ tự.
    """
    results: list[dict] = []
    agency_result: dict | None = None
    user_address = _compose_user_address(user_profile)

    for tc in tool_calls:
        if tc["name"] != "search_agency_place":
            continue

        args = dict(tc.get("args") or {})
        args.setdefault("province", user_profile.get("province", ""))
        args.setdefault("district", user_profile.get("district", ""))
        args.setdefault("ward", user_profile.get("ward", ""))
        result = await _run_tool_call(tc, args=args)
        results.append(result)
        payload = result.get("payload") or {}
        if not payload.get("error") and payload.get("address"):
            agency_result = payload

    for tc in tool_calls:
        if tc["name"] != "get_directions":
            continue

        args = dict(tc.get("args") or {})
        args["origin_address"] = (args.get("origin_address") or user_address).strip()
        if not (args.get("dest_address") or "").strip() and agency_result:
            args["dest_address"] = agency_result.get("address", "")
        if not (args.get("mode") or "").strip():
            args["mode"] = "driving"

        result = await _run_tool_call(tc, args=args)
        results.append(result)

    for tc in tool_calls:
        if tc["name"] in {"search_agency_place", "get_directions"}:
            continue
        results.append(await _run_tool_call(tc))

    return results


async def invoke_llm_with_tools(messages: list) -> AIMessage:
    """Gọi LLM với retry khi gặp rate limit."""
    for attempt in range(MAX_ITER):
        try:
            return await asyncio.to_thread(
                _llm_with_tools.invoke,
                [SystemMessage(content=build_system_prompt()), *messages],
            )
        except Exception as exc:
            is_rate_limit = "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)
            if is_rate_limit and attempt < MAX_ITER - 1:
                wait = (2**attempt) + random.uniform(0, 1)
                logging.warning(
                    f"[location_agent] Rate limit hit (attempt {attempt + 1}/{MAX_ITER}), retrying in {wait:.1f}s..."
                )
                await asyncio.sleep(wait)
                continue
            raise


@traceable
async def location_node(state: AgentState) -> Command[Literal["__end__"]]:
    current_agent = "location"
    next_agent = get_next_agent(state.get("pipeline", []), current_agent)

    qa_answer = state.get("final_response", "")
    user_id = state.get("user_id")
    logging.info(f"[location_agent] User id: {user_id}")

    with next(get_db()) as db:
        user_service = UserService(db)
        user_profile = user_service.get_profile_for_chatbot(user_id) or {}

    user_address = _compose_user_address(user_profile)
    logging.info(f"[location_agent] Starting. user_province={user_profile.get('province')}")

    await emit(
        StreamEvent(
            type="progress",
            node="location",
            message="Đang xác định địa điểm thực hiện thủ tục...",
        )
    )

    if not user_address:
        final_result = _build_fallback_result(
            user_profile=user_profile,
            reason="Thiếu địa chỉ người dùng để tính đường đi. Vui lòng cập nhật địa chỉ trong hồ sơ.",
        )
        summary = final_result["directions_message"]
        await emit(
            StreamEvent(
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
            )
        )
        return Command(
            goto=next_agent,
            update={
                "final_response": summary,
                "messages": [AIMessage(content=summary)],
            },
        )

    messages = [HumanMessage(content=build_user_prompt(qa_answer, user_profile))]
    final_result: dict | None = None
    latest_route: dict | None = None
    latest_agency: dict | None = None

    try:
        for iteration in range(MAX_ITER):
            logging.info(f"[location_agent] Iteration {iteration + 1}/{MAX_ITER}")
            response = await invoke_llm_with_tools(messages)
            logging.info(f"[location_agent] Response location: {_extract_text_content(response.content)[:500]}")

            messages.append(response)
            tool_calls = response.tool_calls or []

            if not tool_calls:
                parsed = _parse_location_response(response.content)
                if parsed:
                    if latest_agency and not parsed.get("agency_name"):
                        parsed["agency_name"] = latest_agency.get("name", "")
                    if latest_route:
                        parsed.setdefault("distance", latest_route.get("distance", ""))
                        parsed.setdefault("duration", latest_route.get("duration", ""))
                        parsed.setdefault("start_address", latest_route.get("start_address", user_address))
                        parsed.setdefault("end_address", latest_route.get("end_address", parsed.get("end_address", "")))
                        if not parsed.get("directions_message"):
                            parsed["directions_message"] = _build_direction_summary(
                                latest_route,
                                agency_name=parsed.get("agency_name", latest_agency.get("name", "") if latest_agency else ""),
                            )
                    final_result = parsed
                    logging.info(f"[location_agent] Got final result on iteration {iteration + 1}")
                else:
                    logging.warning(
                        f"[location_agent] LLM returned non-JSON text: {_extract_text_content(response.content)[:200]}"
                    )
                break

            logging.info(
                f"[location_agent] Executing tools with dependency handling: {[tc['name'] for tc in tool_calls]}"
            )
            tool_results = await execute_tool_calls(tool_calls, user_profile=user_profile)

            for result in tool_results:
                payload = result.get("payload") or {}
                if result.get("name") == "search_agency_place" and not payload.get("error"):
                    latest_agency = payload
                elif result.get("name") == "get_directions" and not payload.get("error"):
                    latest_route = payload

            messages.extend(
                [ToolMessage(content=result["content"], tool_call_id=result["id"]) for result in tool_results]
            )

        if not final_result:
            final_result = _build_fallback_result(
                user_profile=user_profile,
                reason=(latest_route or {}).get("error")
                or "Không thể xác định địa điểm thực hiện thủ tục.",
                agency_name=(latest_agency or {}).get("name", ""),
                end_address=(latest_agency or {}).get("address", ""),
                route=latest_route,
            )

    except Exception as exc:
        logging.error(f"[location_agent] Unexpected error: {exc}", exc_info=True)
        final_result = _build_fallback_result(
            user_profile=user_profile,
            reason="Đã xảy ra lỗi khi tìm địa điểm và tính đường đi.",
            agency_name=(latest_agency or {}).get("name", ""),
            end_address=(latest_agency or {}).get("address", ""),
            route=latest_route,
        )

    summary = final_result.get("directions_message") or "Không thể tạo hướng dẫn đường đi."

    await emit(
        StreamEvent(
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
        )
    )

    return Command(
        goto=next_agent,
        update={
            "final_response": summary,
            "messages": [AIMessage(content=summary)],
        },
    )
