from langchain.tools import tool
from functools import lru_cache
from sqlalchemy import text, bindparam
from sqlalchemy.orm import Session
from app.db.session import get_db
import os
from dotenv import load_dotenv
from app.helpers.utils.logger import logging

load_dotenv()

LEXICAL_SQL = text("""
SELECT
    psi.ma_thu_tuc,
    psi.ten_thu_tuc,
    ts_rank_cd(
        psi.search_tsv,
        websearch_to_tsquery('simple_unaccent', :lexical_query),
        32
    ) AS score
FROM rag.procedure_search_index psi
WHERE psi.search_tsv @@ websearch_to_tsquery('simple_unaccent', :lexical_query)
ORDER BY score DESC, psi.ma_thu_tuc
LIMIT :top_k
""")


def resolve_procedures_fts(
    db: Session,
    user_query: str,
    supervisor_candidates: list[str],
    top_k: int = 2,
    candidate_pool: int = 20,
):
    search_queries = supervisor_candidates[:] if supervisor_candidates else [user_query]
    results = []

    for candidate in search_queries:
        lexical_query = f"{candidate} {user_query}".strip()
        logging.info(f"[FTS] lexical_query: {lexical_query}")  

        rows = db.execute(
            LEXICAL_SQL,
            {
                "lexical_query": lexical_query,
                "top_k": candidate_pool,
            },
        ).mappings().all()
        logging.info(f"[FTS] candidate '{candidate}' → {len(rows)} rows")  
        results.extend(rows)

    if not results:
        logging.warning(f"[FTS] fallback with user_query: {user_query}") 
        rows = db.execute(
            LEXICAL_SQL,
            {
                "lexical_query": candidate,
                "top_k": candidate_pool,
            },
        ).mappings().all()
        logging.info(f"[FTS] fallback → {len(rows)} rows") 
        results.extend(rows)

    dedup = {}
    for row in results:
        key = row["ma_thu_tuc"]
        if key not in dedup or row["score"] > dedup[key]["score"]:
            dedup[key] = dict(row)

    final = sorted(dedup.values(), key=lambda x: x["score"], reverse=True)[:top_k]
    logging.info(f"[FTS] final resolved: {final}") 
    return final


if __name__ == "__main__":
    db = next(get_db())
    user_query = "thủ tục cấp lại CCCD ở tỉnh và trung ương khác nhau thế nào?"
    supervisor_candidates = ["Cấp lại thẻ căn cước"]

    resolve_procedures_fts(db, user_query, supervisor_candidates)