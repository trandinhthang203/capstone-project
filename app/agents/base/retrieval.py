from __future__ import annotations

import asyncio
import os
from typing import Any

from sqlalchemy.orm import joinedload

from app.db.session import SessionLocal
from app.models.procedure import Procedure
from app.models.procedure_group import ProcedureGroup, ProcedureGroupStatus

def _details(code: str, role: str) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        query = (db.query(Procedure).join(ProcedureGroup)
                 .options(joinedload(Procedure.procedure_group))
                 .filter(ProcedureGroup.code == code))
        if role.upper() not in {"EDITOR", "ADMIN"}:
            query = query.filter(ProcedureGroup.status == ProcedureGroupStatus.PUBLISHED)
        rows = query.order_by(Procedure.updated_at.desc()).limit(2).all()
        return [{"source_type": "procedure", "document_id": str(row.id),
                 "procedure_code": row.procedure_group.code, "title": row.name,
                 "passage": "\n".join(filter(None, [row.description, row.steps, row.requirements, row.results])),
                 "url": row.page_url or row.procedure_group.page_url or "",
                 "metadata": {"field": row.field, "authority": row.executing_authority}}
                for row in rows]

async def retrieve_procedures(query: str, role: str, top_k: int = 5) -> list[dict[str, Any]]:
    from scripts.ingestion.indexing import search_procedures
    filters = None if role.upper() in {"EDITOR", "ADMIN"} else {"status": "published"}
    hits = await asyncio.to_thread(search_procedures, query, top_k, filters)
    groups = await asyncio.gather(*(asyncio.to_thread(_details, str(hit["code"]), role)
                                    for hit in hits if hit.get("code")))
    scores = {str(hit.get("code")): float(hit.get("score") or 0) for hit in hits}
    evidence = [item for group in groups for item in group]
    for item in evidence:
        item["score"] = scores.get(item["procedure_code"], 0)
    return evidence[:top_k]

async def retrieve_legal(query: str, entities: dict[str, Any], top_k: int = 8) -> list[dict[str, Any]]:
    from qdrant_client import models as qm
    from app.helpers.utils.init_embedding import _get_client, _get_models
    client = _get_client()
    dense_model, sparse_model = _get_models()
    dense, sparse = await asyncio.gather(
        asyncio.to_thread(lambda: list(dense_model.query_embed(query))[0]),
        asyncio.to_thread(lambda: list(sparse_model.query_embed(query))[0]))
    raw_filter = entities.get("legal_metadata_filter")
    query_filter = (qm.Filter(must=[qm.FieldCondition(key=k, match=qm.MatchValue(value=v))
                                    for k, v in raw_filter.items()]) if isinstance(raw_filter, dict) else None)
    result = await asyncio.to_thread(client.query_points,
        collection_name=os.getenv("QDRANT_LEGAL_COLLECTION", "marriage_family_law"),
        prefetch=[qm.Prefetch(query=dense.tolist(), using="dense", filter=query_filter, limit=top_k),
                  qm.Prefetch(query=qm.SparseVector(indices=sparse.indices.tolist(), values=sparse.values.tolist()),
                              using="sparse", filter=query_filter, limit=top_k)],
        query=qm.FusionQuery(fusion=qm.Fusion.RRF), limit=top_k, with_payload=True)
    evidence = []
    for point in result.points:
        payload = point.payload or {}
        evidence.append({"source_type": "legal", "document_id": str(payload.get("document_id") or point.id),
                         "title": str(payload.get("title") or payload.get("document_name") or "Văn bản pháp luật"),
                         "passage": str(payload.get("passage") or payload.get("text") or payload.get("content") or ""),
                         "url": str(payload.get("source_url") or payload.get("url") or ""),
                         "score": float(point.score or 0), "metadata": payload})
    return evidence
