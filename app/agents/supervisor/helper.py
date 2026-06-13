import json
from app.agents.supervisor.constants import VALID_DOMAINS
from app.helpers.utils.logger import logging
import json
import os
from pathlib import Path

# from scripts.models.procedure import Thu_Tuc
# from scripts.models.basis import Can_Cu_Phap_Ly
# from scripts.models.component import Thanh_Phan_Ho_So
# from scripts.models.method import Cach_Thuc_Thuc_Hien
# from app.db.session import get_db
# from typing import List
# import json

# def get_name_id():
#     with next(get_db()) as db:
#         tts = db.query(Thu_Tuc).all()

#     return tts

# def write_in_json(tts: List[Thu_Tuc], file_path: str):
#     result = {}
#     for tt in tts:
#         result[tt.ten_thu_tuc] = tt.ma_thu_tuc

#     with open(file_path, "w", encoding="utf-8") as file:
#         json.dump(result, file, ensure_ascii=False, indent=2)

# if __name__ == "__main__":
#     tts = get_name_id()
#     write_in_json(tts, "thu_tuc.json")


import re

def _parse_intent_response(raw: str) -> dict:
    try:
        cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logging.warning(f"[intent_node] JSON parse failed: {raw!r}")
        return {
            "intent": "unclear",
            "domain": None,
            "confidence": 0.0,
        }
def _parse_location_response(raw: str) -> dict | None:
    try:
        cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logging.warning(f"[location_agent] JSON parse failed: {raw!r}")
        return None
    
def _validate_domain(domain: str | None) -> str | None:
    if domain and domain.lower() in VALID_DOMAINS:
        return domain.lower()
    return None

def collect_thu_tuc(processed_dir: str, output_file: str = "ket_qua.json"):
    """
    Duyệt qua folder processed, thu thập tên thủ tục từ các file JSON,
    nhóm theo folder con.

    Args:
        processed_dir: Đường dẫn tới folder 'processed'
        output_file:   Tên file JSON kết quả
    """
    processed_path = Path(processed_dir)
    result = {}

    for subfolder in sorted(processed_path.iterdir()):
        if not subfolder.is_dir():
            continue

        folder_name = subfolder.name
        ten_thu_tuc_list = []

        for json_file in sorted(subfolder.glob("*.json")):
            try:
                with open(json_file, encoding="utf-8") as f:
                    data = json.load(f)

                ten = None
                for key, value in data.items():
                    if "tên thủ tục" in key.lower():
                        ten = value
                        break

                if ten:
                    ten_thu_tuc_list.append(ten)
                else:
                    print(f"  [WARN] Không tìm thấy 'Tên thủ tục' trong: {json_file.name}")

            except json.JSONDecodeError as e:
                print(f"  [ERROR] Lỗi parse JSON: {json_file} — {e}")
            except Exception as e:
                print(f"  [ERROR] Lỗi đọc file: {json_file} — {e}")

        result[folder_name] = ten_thu_tuc_list
        print(f"✓ {folder_name}: {len(ten_thu_tuc_list)} thủ tục")

    output_path = Path(output_file)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nXong! Kết quả đã lưu vào: {output_path.resolve()}")
    return result


# if __name__ == "__main__":
#     processed_dir = "data/processed"
#     output_file = "file.json"
#     collect_thu_tuc(processed_dir, output_file)