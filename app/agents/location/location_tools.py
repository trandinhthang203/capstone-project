import httpx
import asyncio
import os
from langchain.tools import tool
from app.helpers.utils.logger import logging

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
_http_client = httpx.AsyncClient(timeout=10.0)


@tool
async def search_agency_place(query: str) -> dict:
    """
    Tìm địa điểm cơ quan nhà nước trên Google Maps theo tên + tỉnh/thành.
    Trả về: name, address, lat, lng, place_id.
    Dùng khi cần tìm địa chỉ thực tế của cơ quan thực hiện thủ tục.

    Args:
        query: Tên cơ quan kèm tỉnh/thành, ví dụ:
               "Phòng cảnh sát quản lý hành chính trật tự xã hội Đà Nẵng"
    """
    resp = await _http_client.get(
        "https://maps.googleapis.com/maps/api/place/textsearch/json",
        params={"query": query, "key": GOOGLE_MAPS_API_KEY, "language": "vi", "region": "VN"},
    )
    data = resp.json()
    if data["status"] != "OK" or not data["results"]:
        logging.warning(f"[search_agency_place] No result for query='{query}': {data['status']}")
        return {"error": f"Không tìm thấy địa điểm cho: {query}"}

    place = data["results"][0]
    loc = place["geometry"]["location"]
    return {
        "name": place["name"],
        "address": place["formatted_address"],
        "lat": loc["lat"],
        "lng": loc["lng"],
        "place_id": place["place_id"],
    }


@tool
async def geocode_user_address(address: str) -> dict:
    """
    Chuyển địa chỉ người dùng thành tọa độ lat/lng.
    Dùng khi cần tọa độ xuất phát để tính đường đi.

    Args:
        address: Địa chỉ đầy đủ của người dùng,
                 ví dụ: "123 Lê Lợi, Quận Hải Châu, Đà Nẵng"
    """
    resp = await _http_client.get(
        "https://maps.googleapis.com/maps/api/geocode/json",
        params={"address": address, "key": GOOGLE_MAPS_API_KEY, "language": "vi", "region": "VN"},
    )
    data = resp.json()
    if data["status"] != "OK" or not data["results"]:
        logging.warning(f"[geocode_user_address] Failed for address='{address}': {data['status']}")
        return {"error": f"Không tìm thấy tọa độ cho: {address}"}

    loc = data["results"][0]["geometry"]["location"]
    return {"lat": loc["lat"], "lng": loc["lng"], "formatted_address": data["results"][0]["formatted_address"]}


@tool
async def get_directions(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
) -> dict:
    """
    Tính đường đi lái xe từ điểm xuất phát đến cơ quan.
    Chỉ gọi sau khi đã có tọa độ cả hai điểm từ search_agency_place và geocode_user_address.

    Args:
        origin_lat: Vĩ độ điểm xuất phát (người dùng)
        origin_lng: Kinh độ điểm xuất phát (người dùng)
        dest_lat:   Vĩ độ đích (cơ quan)
        dest_lng:   Kinh độ đích (cơ quan)
    """
    resp = await _http_client.get(
        "https://maps.googleapis.com/maps/api/directions/json",
        params={
            "origin": f"{origin_lat},{origin_lng}",
            "destination": f"{dest_lat},{dest_lng}",
            "mode": "driving",
            "language": "vi",
            "key": GOOGLE_MAPS_API_KEY,
        },
    )
    data = resp.json()
    if data["status"] != "OK" or not data["routes"]:
        logging.warning(f"[get_directions] Failed: {data['status']}")
        return {"error": "Không thể tính đường đi"}

    leg = data["routes"][0]["legs"][0]
    return {
        "distance": leg["distance"]["text"],
        "duration": leg["duration"]["text"],
        "polyline": data["routes"][0]["overview_polyline"]["points"],
        "steps": [
            {
                "instruction": s["html_instructions"],
                "distance": s["distance"]["text"],
                "duration": s["duration"]["text"],
            }
            for s in leg["steps"]
        ],
    }