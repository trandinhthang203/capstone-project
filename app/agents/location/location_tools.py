import html
import os
import re

import httpx
from langchain.tools import tool

from app.helpers.utils.logger import logging

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
REQUEST_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_http_client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True)
_ALLOWED_MODES = {"driving", "motorcycling", "walking", "truck"}


def _clean_text(value: str) -> str:
    if not value:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", " ", value))
    return re.sub(r"\s+", " ", text).strip()


def _build_query(query: str, province: str = "", district: str = "", ward: str = "") -> str:
    parts: list[str] = []
    for part in (query, ward, district, province):
        if part and part.strip():
            normalized = part.strip()
            if normalized not in parts:
                parts.append(normalized)
    return ", ".join(parts)


async def _get_json(url: str, params: dict) -> dict:
    if not GOOGLE_MAPS_API_KEY:
        logging.error("[location_tools] GOOGLE_MAPS_API_KEY is missing")
        return {"error": "Thiếu cấu hình GOOGLE_MAPS_API_KEY"}

    try:
        resp = await _http_client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()
    except httpx.TimeoutException:
        logging.error(f"[location_tools] Timeout calling {url}", exc_info=True)
        return {"error": "Hệ thống bản đồ phản hồi quá chậm, vui lòng thử lại"}
    except httpx.HTTPStatusError as exc:
        logging.error(
            f"[location_tools] HTTP error {exc.response.status_code} calling {url}",
            exc_info=True,
        )
        return {"error": f"Lỗi dịch vụ bản đồ ({exc.response.status_code})"}
    except ValueError:
        logging.error(f"[location_tools] Invalid JSON response from {url}", exc_info=True)
        return {"error": "Dữ liệu bản đồ trả về không hợp lệ"}
    except Exception as exc:
        logging.error(f"[location_tools] Unexpected error calling {url}: {exc}", exc_info=True)
        return {"error": "Không thể kết nối dịch vụ bản đồ"}


@tool
async def search_agency_place(query: str) -> dict:
    """
    Tìm địa điểm cơ quan nhà nước trên bản đồ theo tên cơ quan và gợi ý khu vực.

    Args:
        query: Tên cơ quan hoặc mô tả cơ quan cần tìm.
        province: Tỉnh/thành phố của người dùng hoặc nơi thực hiện thủ tục.
        district: Quận/huyện gợi ý.
        ward: Phường/xã gợi ý.
    """
    if not query or not query.strip():
        return {"error": "Thiếu tên cơ quan cần tìm"}

    # query_used = _build_query(query, province=province, district=district, ward=ward)
    data = await _get_json(
        "https://maps.mapvina.com/api/v2/place/autocomplete/json",
        params={
            "input": query,
            "key": GOOGLE_MAPS_API_KEY,
            "size": 5,
        },
    )

    if data.get("error"):
        return data

    predictions = [p for p in data.get("predictions", []) if p.get("description")]
    if data.get("status") != "OK" or not predictions:
        logging.warning(f"[search_agency_place] No result for query='{query}': {data}")
        return {
            "error": f"Không tìm thấy địa điểm phù hợp cho: {query}",
            "query_used": query,
        }

    place = predictions[0]
    return {
        "end_address": place.get("description", ""),
        "query_used": query,
    }


@tool
async def get_directions(
    origin_address: str,
    dest_address: str,
    mode: str = "driving",
) -> dict:
    """
    Tính đường đi từ địa chỉ người dùng đến địa chỉ cơ quan.

    Args:
        origin_address: Địa chỉ điểm xuất phát: là địa chỉ của người dùng .
        dest_address: Địa chỉ đích: là địa chỉ của cơ quan.
        mode: driving, motorcycling, walking, truck.
    """
    origin_address = (origin_address or "").strip()
    dest_address = (dest_address or "").strip()

    if not origin_address:
        return {"error": "Thiếu địa chỉ xuất phát của người dùng"}
    if not dest_address:
        return {"error": "Thiếu địa chỉ cơ quan để tính đường đi"}

    mode = mode if mode in _ALLOWED_MODES else "driving"
    data = await _get_json(
        "https://maps.mapvina.com/route/v2/directions/json",
        params={
            "origin": origin_address,
            "destination": dest_address,
            "mode": mode,
            "key": GOOGLE_MAPS_API_KEY,
        },
    )

    if data.get("error"):
        return data

    routes = data.get("routes") or []
    if data.get("status") != "OK" or not routes:
        logging.warning(
            f"[get_directions] Failed for origin='{origin_address}' dest='{dest_address}': {data}"
        )
        return {
            "error": "Không thể tính đường đi giữa hai địa chỉ đã cung cấp",
            "status": data.get("status", "UNKNOWN"),
            "start_address": origin_address,
            "end_address": dest_address,
        }

    legs = routes[0].get("legs") or []
    leg = legs[0] if legs else {}
    steps = []
    for step in leg.get("steps", []):
        steps.append(
            {
                "instruction": _clean_text(step.get("html_instructions", "")),
                "distance": step.get("distance", {}).get("text", ""),
                "duration": step.get("duration", {}).get("text", ""),
                "maneuver": step.get("maneuver", ""),
            }
        )

    return {
        "mode": mode,
        "distance": leg.get("distance", {}).get("text", ""),
        "duration": leg.get("duration", {}).get("text", ""),
        "start_address": leg.get("start_address") or origin_address,
        "end_address": leg.get("end_address") or dest_address,
        "polyline": routes[0].get("overview_polyline", {}).get("points", ""),
        "steps": steps,
    }
