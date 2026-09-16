"""
build_dataset.py
----------------
Chạy luồng từ đầu đến qa_node để lấy context thực tế (compact_ctx)
cho mỗi câu hỏi trong ragas_fixed.csv, sau đó ghi vào cột "context".

Luồng:
  question → [Qdrant retrieve] → [LLM intent router] → [DB query] → _compact_payload → context

Không gọi get_response_llm ở bước cuối để tiết kiệm chi phí.
"""

from app.helpers.utils import logger
import asyncio
import sys
import os
from langchain_core.messages import HumanMessage

# ── đảm bảo import được app từ root project ──
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
load_dotenv()

import pandas as pd
from tqdm import tqdm

from app.agents.supervisor.qdrant_retriever import retrieve_procedures
from app.agents.supervisor.helper import _parse_intent_response, _normalize_pipeline
from app.agents.supervisor.constants import CONFIDENCE_THRESHOLD
from app.agents.supervisor.supervisor_node import DEFAULT_QA_FIELDS, RETRIEVE_TOP_K, _name_ids
from app.core.config import supervisor_prompt
from app.helpers.utils.common import get_response_llm, read_json
from app.agents.qa.helper import _compact_payload, QA_DEFAULT_FIELDS, _run_initial_query_async
from app.helpers.utils.logger import logging

CSV_PATH = "data/evaluation/ragas_fixed_1.csv"


async def get_context_for_question(question: str) -> str:
    """
    Chạy luồng: retrieve → intent_router (LLM) → DB query → compact_payload.
    Trả về compact_ctx string, hoặc "" nếu không lấy được.
    """
    # ── Bước 1: Qdrant retrieve ──
    try:
        candidate_hits = await retrieve_procedures(question, top_k=RETRIEVE_TOP_K)
        logging.info(f"[INFO] Candidates: {candidate_hits}")
    except Exception as e:
        logging.error("[build_dataset] Qdrant error: %s", e)
        return ""

    candidate_names = [h["ten_thu_tuc"] for h in candidate_hits]
    procedures_block = "\n".join(f"- {name}" for name in candidate_names) or "[]"

    # ── Bước 2: LLM intent router (để lấy procedure_ids + fields chính xác) ──
    prompt = supervisor_prompt["SUPERVISOR_PROMPT_V3"].format(
        query=question,
        raw_query=question,
        procedures=procedures_block,
        last_domain="[]",
        last_procedures="[]",
    )

    try:
        raw = await get_response_llm(
            prompt=prompt,
            messages=[HumanMessage(content=question)],
            summary="",
            max_messages=1,
        )
        data = _parse_intent_response(raw)
    except Exception as e:
        logging.error("[build_dataset] LLM intent error: %s", e)
        return ""

    intent = data.get("intent", "unclear")
    confidence = float(data.get("confidence", 0.0))
    procedures = data.get("procedures", []) or []
    fields = data.get("fields", []) or QA_DEFAULT_FIELDS

    logging.info(f"[retrieve] Danh sách thủ tục: {procedures}, confidence: {confidence}, fields: {fields}")

    if confidence < CONFIDENCE_THRESHOLD:
        intent = "unclear"

    # Lọc chỉ giữ thủ tục nằm trong candidate
    if procedures:
        valid_names = set(candidate_names)
        procedures = [p for p in procedures if p in valid_names]

    # Map tên → mã thủ tục
    name_ids_map = _name_ids()
    procedure_ids = [name_ids_map[p] for p in procedures if p in name_ids_map]
    logging.info(f"[retrieve] procedure_ids: {procedure_ids}") 

    if intent in ("chitchat", "unclear") or not procedure_ids:
        logging.warning("[build_dataset] intent=%s, procedure_ids=%s → skip", intent, procedure_ids)
        return ""

    # ── Bước 3: Query DB ──
    try:
        initial_payload = await _run_initial_query_async(procedure_ids, fields)
    except Exception as e:
        logging.error("[build_dataset] DB query error: %s", e)
        return ""

    # ── Bước 4: compact_payload ──
    compact_ctx = _compact_payload(initial_payload)
    return compact_ctx


async def main():
    df = pd.read_csv(CSV_PATH, encoding="utf-8")
    print(f"[INFO] Loaded {len(df)} rows from {CSV_PATH}")
    print(f"[INFO] Columns: {df.columns.tolist()}")

    if "context" not in df.columns:
        df["context"] = ""

    contexts = []
    for i, row in tqdm(df.iterrows(), total=len(df), desc="Building contexts"):
        question = str(row.get("question", "")).strip()
        if not question:
            contexts.append("")
            continue

        ctx = await get_context_for_question(question)
        contexts.append(ctx)
        print(f"  [{i+1}/{len(df)}] question: {question[:60]}...")
        print(f"         context length: {len(ctx)} chars")

    df["context"] = contexts
    df.to_csv(CSV_PATH, index=False, encoding="utf-8")
    print(f"\n[DONE] Saved {len(df)} rows with context to {CSV_PATH}")

    # Thống kê
    filled = sum(1 for c in contexts if c)
    print(f"[STAT] Filled: {filled}/{len(df)} rows  |  Empty: {len(df)-filled}/{len(df)}")


if __name__ == "__main__":
    asyncio.run(main())