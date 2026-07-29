from __future__ import annotations

import os
from functools import lru_cache
from typing import Any
from app.helpers.utils.logger import logging
from app.helpers.utils.init_embedding import _get_client, _get_models, COLLECTION_NAME

def _search_sync(query: str, top_k: int = 15, linh_vuc: str | None = None) -> list[dict[str, Any]]:
    """
    Thực hiện hybrid search (dense + BM25 → RRF fusion).

    Args:
        query:     Câu truy vấn của người dùng (đã được resolve followup).
        top_k:     Số kết quả trả về.
        linh_vuc:  (Tuỳ chọn) Lọc theo lĩnh vực nếu đã biết.

    Returns:
        Danh sách dict: {"ma_so", "ten_thu_tuc", "linh_vuc", "score", ...}
    """
    from qdrant_client import models as qm  

    client = _get_client()
    dense_model, sparse_model = _get_models()

    # Embed query
    dense_vec = list(dense_model.embed([query]))[0]
    sparse_vec = list(sparse_model.embed([query]))[0]

    # Build optional filter
    query_filter = None
    if linh_vuc:
        query_filter = qm.Filter(
            must=[
                qm.FieldCondition(
                    key="linh_vuc",
                    match=qm.MatchValue(value=linh_vuc),
                )
            ]
        )

    results = client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            qm.Prefetch(
                query=dense_vec.tolist(),
                using="dense",
                limit=top_k * 2,
                filter=query_filter,
            ),
            qm.Prefetch(
                query=qm.SparseVector(
                    indices=sparse_vec.indices.tolist(),
                    values=sparse_vec.values.tolist(),
                ),
                using="bm25",
                limit=top_k * 2,
                filter=query_filter,
            ),
        ],
        query=qm.FusionQuery(fusion=qm.Fusion.RRF),
        limit=top_k,
    )

    hits = []
    for point in results.points:
        payload = point.payload or {}
        hits.append(
            {
                "ma_so": payload.get("ma_so", ""),
                "ten_thu_tuc": payload.get("ten_thu_tuc", ""),
                "linh_vuc": payload.get("linh_vuc", ""),
                "co_quan_ban_hanh": payload.get("co_quan_ban_hanh", ""),
                "co_quan_thuc_hien": payload.get("co_quan_thuc_hien", ""),
                "score": point.score,
            }
        )

    logging.info(
        "[qdrant_retriever] query=%r top_k=%d → %d hits",
        query[:60],
        top_k,
        len(hits),
    )
    return hits


async def retrieve_procedures(
    query: str,
    top_k: int = 15,
    linh_vuc: str | None = None,
) -> list[dict[str, Any]]:
    """
    Async wrapper cho _search_sync.
    Chạy trong executor để không block event loop.
    """
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _search_sync, query, top_k, linh_vuc
    )
