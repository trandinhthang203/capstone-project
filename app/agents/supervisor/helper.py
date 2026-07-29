import json
import re
from pathlib import Path
from typing import Any

from app.agents.supervisor.constants import VALID_DOMAINS
from app.helpers.utils.logger import logging


def _normalize_pipeline(pipeline: list) -> list[str]:
    allowed_agents = {"qa", "forms", "location"}
    flat: list[str] = []
    seen: set[str] = set()

    for item in pipeline or ["qa"]:
        candidates = [item] if isinstance(item, str) else item if isinstance(item, list) else []
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            candidate = candidate.strip()
            if candidate not in allowed_agents or candidate in seen:
                continue
            flat.append(candidate)
            seen.add(candidate)

    return flat or ["qa"]


def _resolve_first_agent(pipeline: list[str], procedures: list[str]) -> str:
    if not procedures:
        return "qa"
    return pipeline[0] if pipeline else "qa"


def _format_candidates_for_llm(hits: list[dict]) -> str:
    """Chuyển danh sách hit từ Qdrant thành chuỗi liệt kê để đưa vào prompt LLM."""
    lines = []
    for i, h in enumerate(hits, 1):
        name = h.get("ten_thu_tuc", "")
        linh_vuc = h.get("linh_vuc", "")
        lines.append(f"{i}. {name}" + (f" (Lĩnh vực: {linh_vuc})" if linh_vuc else ""))
    return "\n".join(lines)


def _normalize_model_output(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        text = raw.get("text")
        if isinstance(text, str):
            return text.strip()
        return json.dumps(raw, ensure_ascii=False)
    if isinstance(raw, list):
        chunks: list[str] = []
        for item in raw:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
        if chunks:
            return "\n".join(chunks).strip()
        return json.dumps(raw, ensure_ascii=False)
    return str(raw).strip()


def _parse_intent_response(raw: Any) -> dict:
    try:
        cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", _normalize_model_output(raw)).strip()
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logging.warning(f"[intent_node] JSON parse failed: {raw!r}")
        return {
            "intent": "unclear",
            "domain": None,
            "confidence": 0.0,
        }


def _parse_location_response(raw: Any) -> dict | None:
    try:
        cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", _normalize_model_output(raw)).strip()
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
