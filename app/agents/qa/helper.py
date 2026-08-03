import json
from app.agents.base.state import SupervisorOutput
from app.agents.qa.qa_tools import (
    TABLE_COLUMNS,
    build_query_plan,
    execute_query_plan,
)
import asyncio

QA_DEFAULT_FIELDS = [
    "thu_tuc.ten_thu_tuc",
    "thu_tuc.linh_vuc",
    "thu_tuc.trinh_tu_thuc_hien",
    "thu_tuc.doi_tuong_thuc_hien",
    "thu_tuc.co_quan_thuc_hien",
    "thu_tuc.co_quan_co_tham_quyen",
    "thu_tuc.dia_chi_tiep_nhan_hs",
    "thu_tuc.yeu_cau_dieu_kien",
    "thu_tuc.ket_qua_thuc_hien",
    "thu_tuc.ket_qua_thuc_hien", 
    "thu_tuc.tu_khoa",
    "thu_tuc.mo_ta",
]


def _compact_payload(payload: dict, max_rows_per_table: int = 6) -> str:
    """
    Rút gọn payload DB về dạng ngắn gọn để đưa vào prompt LLM.
    Giảm ~70% token so với json.dumps toàn bộ rows.
    """
    def short_row(r: dict) -> dict:
        return {k: (v if isinstance(v, (int, float)) or not v else str(v)[:300])
                for k, v in r.items() if v not in (None, "", [], {})}

    main_rows = payload.get("main", {}).get("rows", []) or []
    children = payload.get("children", {}) or {}
    out = {
        "procedures": [
            {k: short_row(r).get(k) for k in ("ma_thu_tuc", "ten_thu_tuc", "trinh_tu_thuc_hien",
                                                "co_quan_thuc_hien", "dia_chi_tiep_nhan_hs",
                                                "yeu_cau_dieu_kien", "ket_qua_thuc_hien")}
            for r in main_rows[:max_rows_per_table]
        ],
        "forms": [short_row(r) for r in (children.get("thanh_phan_ho_so", {}).get("rows", []) or [])[:max_rows_per_table]],
        "process": [short_row(r) for r in (children.get("cach_thuc_thuc_hien", {}).get("rows", []) or [])[:max_rows_per_table]],
        "legal_basis": [short_row(r) for r in (children.get("can_cu_phap_ly", {}).get("rows", []) or [])[:3]],
    }
    return json.dumps(out, ensure_ascii=False)


def _build_qa_one_pass_prompt(user_input: str, procedure_names: list[str],
                                procedure_ids: list[str], context: str,
                                pipeline: list[str]) -> str:
    return f"""Bạn là trợ lý thủ tục hành chính Việt Nam. Nhiệm vụ: trả lời DUY NHẤT 1 LẦN (không self-eval).

Câu hỏi: {user_input}

Thủ tục đã match: {json.dumps(procedure_names, ensure_ascii=False)}
Mã thủ tục: {json.dumps(procedure_ids)}

Dữ liệu từ cơ sở dữ liệu (đã được rút gọn):
{context}

Pipeline phía sau: {json.dumps(pipeline)}

QUY TẮC BẮT BUỘC (áp dụng trong 1 câu trả lời duy nhất):
1. Grounded: chỉ dùng thông tin có trong dữ liệu trên. Tuyệt đối không bịa.
2. Đủ ý chính theo câu hỏi, tiếng Việt tự nhiên, có cấu trúc Markdown.
3. Nếu dữ liệu thiếu, nói rõ phần thiếu.
4. Nếu có link S3 từ cột mau_don_to_khai, giữ nguyên link Markdown.
5. Nếu pipeline có "forms", KHÔNG hướng dẫn điền biểu mẫu, chỉ trả lời thông tin.

Trả lời:"""


async def _run_initial_query_async(procedure_ids: list[str], default_fields: list[str]) -> dict:
    """Chạy SQL build + execute trong thread pool, không block event loop."""
    case = SupervisorOutput(procedures=procedure_ids, fields=default_fields)

    def _sync():
        plan = build_query_plan(case)
        return execute_query_plan(plan, case.procedures)

    return await asyncio.to_thread(_sync)