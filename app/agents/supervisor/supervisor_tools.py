from langchain.tools import tool
from functools import lru_cache
from sqlalchemy import text, bindparam
from sqlalchemy.orm import Session
from pgvector.sqlalchemy import Vector
from langchain_huggingface import HuggingFaceEmbeddings
import os
from dotenv import load_dotenv
from app.helpers.utils.logger import logging

load_dotenv()

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM"))

_embedder = HuggingFaceEmbeddings(
    model_name=os.getenv("EMBEDDING_MODEL"),
    model_kwargs={"trust_remote_code": True},
    encode_kwargs={"normalize_embeddings": True},
)


@lru_cache(maxsize=512)
def _embed_query_cached(query: str):
    return tuple(_embedder.embed_query(query))


HYBRID_SQL = text("""
WITH lexical AS (
    SELECT
        psi.ma_thu_tuc,
        psi.ten_thu_tuc,
        row_number() OVER (
            ORDER BY ts_rank_cd(
                psi.search_tsv,
                websearch_to_tsquery('simple_unaccent', :lexical_query),
                32
            ) DESC,
            psi.ma_thu_tuc
        ) AS lexical_rank
    FROM rag.procedure_search_index psi
    WHERE psi.search_tsv @@ websearch_to_tsquery('simple_unaccent', :lexical_query)
    ORDER BY lexical_rank
    LIMIT :candidate_pool
),
semantic AS (
    SELECT
        psi.ma_thu_tuc,
        psi.ten_thu_tuc,
        row_number() OVER (
            ORDER BY psi.embedding <=> :query_embedding, psi.ma_thu_tuc
        ) AS semantic_rank
    FROM rag.procedure_search_index psi
    ORDER BY psi.embedding <=> :query_embedding, psi.ma_thu_tuc
    LIMIT :candidate_pool
),
fused AS (
    SELECT
        COALESCE(l.ma_thu_tuc, s.ma_thu_tuc) AS ma_thu_tuc,
        COALESCE(l.ten_thu_tuc, s.ten_thu_tuc) AS ten_thu_tuc,
        COALESCE(1.0 / (:rrf_k + l.lexical_rank), 0.0) +
        COALESCE(1.0 / (:rrf_k + s.semantic_rank), 0.0) AS score
    FROM lexical l
    FULL OUTER JOIN semantic s
      ON l.ma_thu_tuc = s.ma_thu_tuc
)
SELECT ma_thu_tuc, ten_thu_tuc, score
FROM fused
ORDER BY score DESC, ma_thu_tuc
LIMIT :top_k
""").bindparams(
    bindparam("query_embedding", type_=Vector(EMBEDDING_DIM))
)


def resolve_procedures_hybrid(
    db: Session,
    user_query: str,
    supervisor_candidates: list[str],
    top_k: int = 1,
    candidate_pool: int = 20,
    rrf_k: int = 60,
):
    search_queries = supervisor_candidates[:] if supervisor_candidates else [user_query]
    results = []

    for candidate in search_queries:
        lexical_query = f"{candidate} {user_query}".strip()
        query_embedding = _embed_query_cached(candidate.strip() or user_query.strip())

        row = db.execute(
            HYBRID_SQL,
            {
                "lexical_query": lexical_query,
                "query_embedding": query_embedding,
                "candidate_pool": candidate_pool,
                "top_k": top_k,
                "rrf_k": rrf_k,
            },
        ).mappings().first()

        if row:
            logging.info(f"[supervisor_tool] row: {dict(row)}")
            results.append(dict(row))

    if not results:
        query_embedding = _embed_query_cached(user_query.strip())
        row = db.execute(
            HYBRID_SQL,
            {
                "lexical_query": user_query,
                "query_embedding": query_embedding,
                "candidate_pool": candidate_pool,
                "top_k": top_k,
                "rrf_k": rrf_k,
            },
        ).mappings().first()

        if row:
            results.append(dict(row))

    return results

