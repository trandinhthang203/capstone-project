import httpx
import os
from langchain.tools import tool
from app.helpers.utils.logger import logging

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
_http_client = httpx.AsyncClient(timeout=10.0)

@tool
async def search_agency_place(query: str) -> dict:
    """
    Tìm địa điểm cơ quan nhà nước trên Mapvina theo tên + tỉnh/thành hoặc xã phường.
    Trả về: name, address, place_id, reference
    Dùng khi cần tìm địa chỉ thực tế của cơ quan thực hiện thủ tục.

    Args:
        query: Tên cơ quan kèm tỉnh/thành hoặc xã phường, ví dụ:
               "Phòng cảnh sát quản lý hành chính trật tự xã hội Đà Nẵng"
    """
    resp = await _http_client.get(
        "https://maps.mapvina.com/api/v2/place/autocomplete/json",
        params={
            "input": query,
            "key": GOOGLE_MAPS_API_KEY,
            "size": 1,
        },
    )
    data = resp.json()

    if data.get("status") != "OK":
        logging.warning(f"[search_agency_place] No result for query='{query}': {data}")
        return {"error": f"Không tìm thấy địa điểm cho: {query}"}

    predictions = data.get("predictions", [])
    if not predictions:
        return {"error": f"Không tìm thấy địa điểm cho: {query}"}

    place = predictions[0]
    return {
        "name": place.get("name", ""),
        "address": place.get("description", ""),  # dùng description, có đầy đủ tên + địa chỉ
        "place_id": place.get("place_id", ""),
        "reference": place.get("reference", ""),
    }

# @tool
# async def search_agency_place(query: str) -> dict:
#     """
#     Tìm địa điểm cơ quan nhà nước trên Google Maps theo tên + tỉnh/thành hoặc xã phường.
#     Trả về: name, address, lat, lng, place_id.
#     Dùng khi cần tìm địa chỉ thực tế của cơ quan thực hiện thủ tục.

#     Args:
#         query: Tên cơ quan kèm tỉnh/thành hoặc xã phường, ví dụ:
#                "Phòng cảnh sát quản lý hành chính trật tự xã hội Đà Nẵng"
#     """
#     resp = await _http_client.get(
#         "https://maps.googleapis.com/maps/api/place/findplacefromtext/json",
#         params={
#             "input": query,
#             "inputtype": "textquery",
#             "fields": "name,formatted_address,geometry,place_id",
#             "language": "vi",
#             "key": GOOGLE_MAPS_API_KEY,
#         },
#     )
#     data = resp.json()

#     if data.get("status") != "OK":
#         logging.warning(f"[search_agency_place] No result for query='{query}': {data}")
#         return {"error": f"Không tìm thấy địa điểm cho: {query}"}

#     place = data["candidates"][0]
#     return {
#         "name": place["name"],
#         "address": place["formatted_address"],
#         "lat": place["geometry"]["location"]["lat"],
#         "lng": place["geometry"]["location"]["lng"],
#         "place_id": place.get("place_id", ""),
#     }


# @tool
# async def geocode_user_address(address: str) -> dict:
#     """
#     Chuyển địa chỉ người dùng thành tọa độ lat/lng.
#     Dùng khi cần tọa độ xuất phát để tính đường đi.

#     Args:
#         address: Địa chỉ đầy đủ của người dùng,
#                  ví dụ: "123 Lê Lợi, Quận Hải Châu, Đà Nẵng"
#     """
#     resp = await _http_client.get(
#         "https://maps.googleapis.com/maps/api/geocode/json",
#         params={
#             "address": address,
#             "key": GOOGLE_MAPS_API_KEY,
#             "language": "vi",
#             "region": "VN",
#         },
#     )
#     data = resp.json()
#     if data["status"] != "OK" or not data["results"]:
#         logging.warning(f"[geocode_user_address] Failed for address='{address}': {data['status']}")
#         return {"error": f"Không tìm thấy tọa độ cho: {address}"}

#     loc = data["results"][0]["geometry"]["location"]
#     return {
#         "lat": loc["lat"],
#         "lng": loc["lng"],
#         "formatted_address": data["results"][0]["formatted_address"],
#     }

@tool
async def get_directions(
    origin_address: str,
    dest_address: str,
    mode: str = "driving",
) -> dict:
    """
    Tính đường đi từ điểm xuất phát đến cơ quan theo địa chỉ.
    Chỉ gọi sau khi đã có địa chỉ cả hai điểm.

    Args:
        origin_address: Địa chỉ điểm xuất phát (người dùng), ví dụ: "2 Nguyễn Huệ, phường Sài Gòn, thành phố Hồ Chí Minh"
        dest_address:   Địa chỉ đích (cơ quan), ví dụ: "Phòng cảnh sát quản lý hành chính, Đà Nẵng"
        mode:           Phương thức di chuyển: driving (mặc định), motorcycling, walking, truck
    """
    resp = await _http_client.get(
        "https://maps.mapvina.com/route/v2/directions/json",
        params={
            "origin": origin_address,
            "destination": dest_address,
            "mode": mode,
            "key": GOOGLE_MAPS_API_KEY,
        },
    )
    data = resp.json()

    if data.get("status") != "OK" or not data.get("routes"):
        logging.warning(f"[get_directions] Failed: {data.get('status')}")
        return {"error": "Không thể tính đường đi"}

    # location_tools.py - get_directions
    leg = data["routes"][0]["legs"][0]
    return {
        "distance": leg["distance"]["text"],
        "duration": leg["duration"]["text"],
        "start_address": leg.get("start_address", ""),
        "end_address": leg.get("end_address", ""),
        "polyline": data["routes"][0].get("overview_polyline", {}).get("points", ""),  # fix: lấy .points
        "steps": [
            {
                "instruction": s.get("html_instructions", ""),
                "distance": s["distance"]["text"],
                "duration": s["duration"]["text"],
                "maneuver": s.get("maneuver", ""),
            }
            for s in leg.get("steps", [])
        ],
    }