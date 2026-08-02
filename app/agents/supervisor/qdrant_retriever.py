from __future__ import annotations
import asyncio
import time
from functools import lru_cache
from typing import Any

from cachetools import TTLCache                                          # pip install cachetools
from app.helpers.utils.logger import logging
from app.helpers.utils.init_embedding import _get_client, _get_models, COLLECTION_NAME

# ↓ Cache 256 query cho 5 phút. Chỉ cache khi query ≠ followup.
_RETRIEVE_CACHE: TTLCache = TTLCache(maxsize=256, ttl=300)


def _search_sync(query: str, top_k: int = 8, linh_vuc: str | None = None) -> list[dict[str, Any]]:
    from qdrant_client import models as qm

    client = _get_client()
    dense_model, sparse_model = _get_models()

    dense_vec = list(dense_model.embed([query]))[0]
    sparse_vec = list(sparse_model.embed([query]))[0]

    query_filter = None
    if linh_vuc:
        query_filter = qm.Filter(must=[qm.FieldCondition(
            key="linh_vuc", match=qm.MatchValue(value=linh_vuc))])

    # ↓ limit=8 thay vì `top_k*2=16` — tránh overfetch.
    results = client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            qm.Prefetch(query=dense_vec.tolist(), using="dense",
                        limit=top_k, filter=query_filter),
            qm.Prefetch(query=qm.SparseVector(
                            indices=sparse_vec.indices.tolist(),
                            values=sparse_vec.values.tolist()),
                        using="bm25",
                        limit=top_k, filter=query_filter),
        ],
        query=qm.FusionQuery(fusion=qm.Fusion.RRF),
        limit=top_k,
    )
    hits = []
    for point in results.points:
        payload = point.payload or {}
        hits.append({
            "ma_so": payload.get("ma_so", ""),
            "ten_thu_tuc": payload.get("ten_thu_tuc", ""),
            "linh_vuc": payload.get("linh_vuc", ""),
            "score": point.score,
        })
    return hits


async def retrieve_procedures(query: str, top_k: int = 8,
                                linh_vuc: str | None = None) -> list[dict[str, Any]]:
    """
    Async + cache theo (query_normalized, top_k). Hỗ trợ dedup cho followup.
    """
    key = (query.strip().lower(), top_k, linh_vuc or "")
    cached = _RETRIEVE_CACHE.get(key)
    if cached is not None:
        return cached

    loop = asyncio.get_event_loop()
    hits = await loop.run_in_executor(None, _search_sync, query, top_k, linh_vuc)
    _RETRIEVE_CACHE[key] = hits
    logging.info("[qdrant_retriever] query=%r top_k=%d → %d hits (CACHED=%s)",
                 query[:60], top_k, len(hits), key in _RETRIEVE_CACHE)
    return hits
