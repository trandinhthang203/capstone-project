"""Đồng bộ bảng ``procedures`` lên Qdrant và tìm kiếm hybrid.

Mỗi ProcedureGroup là một Qdrant point/chunk. Point ID được giữ ổn định bằng
chính ProcedureGroup.id nên chạy lại job sẽ upsert thay vì tạo dữ liệu trùng.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from typing import Any

from qdrant_client import models as qm
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.helpers.utils.init_embedding import COLLECTION_NAME, _get_client, _get_models
from app.models.procedure_group import ProcedureGroup, ProcedureGroupStatus


DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "bm25"
PAYLOAD_INDEX_FIELDS = (
    "code",
    "name",
    "issuing_agency",
    "implementing_agency",
    "domain",
)


def _chunks(items: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _embedding_text(procedure: ProcedureGroup) -> str:
    """Mỗi tên thủ tục là đúng một chunk; các trường khác chỉ là metadata."""
    return procedure.name.strip()


def _payload(procedure: ProcedureGroup) -> dict[str, str | None]:
    return {
        "procedure_group_id": str(procedure.id),
        "code": procedure.code,
        "name": procedure.name,
        "issuing_agency": procedure.issuing_agency,
        "implementing_agency": procedure.implementing_agency,
        "domain": procedure.domain,
    }


def _ensure_collection(client: Any, dense_size: int) -> None:
    """Tạo collection và payload indexes nếu chúng chưa tồn tại."""
    if not client.collection_exists(COLLECTION_NAME):
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                DENSE_VECTOR_NAME: qm.VectorParams(
                    size=dense_size,
                    distance=qm.Distance.COSINE,
                )
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: qm.SparseVectorParams(modifier=qm.Modifier.IDF)
            },
        )

    # Qdrant coi thao tác tạo lại cùng payload index là idempotent.
    for field in PAYLOAD_INDEX_FIELDS:
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=field,
            field_schema=qm.PayloadSchemaType.KEYWORD,
            wait=True,
        )


def upsert_procedures(
    db: Session | None = None,
    batch_size: int = 64,
) -> dict[str, int | str]:
    """Upsert các ProcedureGroup archived rồi chuyển chúng sang published.

    Chỉ cập nhật trạng thái sau khi mọi batch đã được Qdrant xác nhận. Nếu có
    lỗi, transaction database được rollback; các point đã ghi dở vẫn an toàn
    vì point ID ổn định và sẽ được upsert lại ở lần chạy tiếp theo.
    """
    if batch_size < 1:
        raise ValueError("batch_size phải lớn hơn 0")

    owns_session = db is None
    session = db or SessionLocal()
    try:
        procedures = (
            session.query(ProcedureGroup)
            .filter(ProcedureGroup.status == ProcedureGroupStatus.DRAFT)
            .order_by(ProcedureGroup.code)
            .all()
        )
        if not procedures:
            return {"collection": COLLECTION_NAME, "upserted": 0}

        client = _get_client()
        dense_model, sparse_model = _get_models()
        upserted = 0
        collection_ready = False

        for batch in _chunks(procedures, batch_size):
            texts = [_embedding_text(procedure) for procedure in batch]
            dense_vectors = list(dense_model.passage_embed(texts))
            sparse_vectors = list(sparse_model.passage_embed(texts))
            if not dense_vectors:
                continue

            if not collection_ready:
                _ensure_collection(client, len(dense_vectors[0]))
                collection_ready = True
            points = []
            for procedure, dense, sparse in zip(
                batch, dense_vectors, sparse_vectors, strict=True
            ):
                points.append(
                    qm.PointStruct(
                        id=str(procedure.id),
                        vector={
                            DENSE_VECTOR_NAME: dense.tolist(),
                            SPARSE_VECTOR_NAME: qm.SparseVector(
                                indices=sparse.indices.tolist(),
                                values=sparse.values.tolist(),
                            ),
                        },
                        payload=_payload(procedure),
                    )
                )
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=points,
                wait=True,
            )
            upserted += len(points)

        for procedure in procedures:
            procedure.status = ProcedureGroupStatus.PUBLISHED
        session.commit()
        return {"collection": COLLECTION_NAME, "upserted": upserted}
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


def _build_filter(filters: dict[str, str] | None) -> qm.Filter | None:
    if not filters:
        return None
    invalid = set(filters) - set(PAYLOAD_INDEX_FIELDS)
    if invalid:
        raise ValueError(f"Trường filter không hợp lệ: {', '.join(sorted(invalid))}")
    return qm.Filter(
        must=[
            qm.FieldCondition(key=field, match=qm.MatchValue(value=value))
            for field, value in filters.items()
        ]
    )


def search_procedures(
    query: str,
    top_k: int = 8,
    filters: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Hybrid search dense + BM25, hợp nhất thứ hạng bằng RRF."""
    query = query.strip()
    if not query:
        raise ValueError("query không được để trống")
    if top_k < 1:
        raise ValueError("top_k phải lớn hơn 0")

    client = _get_client()
    dense_model, sparse_model = _get_models()
    dense = list(dense_model.query_embed(query))[0]
    sparse = list(sparse_model.query_embed(query))[0]
    query_filter = _build_filter(filters)

    result = client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            qm.Prefetch(
                query=dense.tolist(),
                using=DENSE_VECTOR_NAME,
                filter=query_filter,
                limit=top_k,
            ),
            qm.Prefetch(
                query=qm.SparseVector(
                    indices=sparse.indices.tolist(),
                    values=sparse.values.tolist(),
                ),
                using=SPARSE_VECTOR_NAME,
                filter=query_filter,
                limit=top_k,
            ),
        ],
        query=qm.FusionQuery(fusion=qm.Fusion.RRF),
        limit=top_k,
        with_payload=True,
    )

    return [
        {
            "procedure_group_id": (point.payload or {}).get("procedure_group_id"),
            "code": (point.payload or {}).get("code"),
            "name": (point.payload or {}).get("name"),
            "score": point.score,
        }
        for point in result.points
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Index/search ProcedureGroup trên Qdrant")
    subparsers = parser.add_subparsers(dest="command", required=True)
    index_parser = subparsers.add_parser("index", help="Upsert dữ liệu lên Qdrant")
    index_parser.add_argument("--batch-size", type=int, default=64)
    search_parser = subparsers.add_parser("search", help="Thử hybrid search")
    search_parser.add_argument("query")
    search_parser.add_argument("--top-k", type=int, default=8)
    args = parser.parse_args()

    if args.command == "index":
        print(upsert_procedures(batch_size=args.batch_size))
    else:
        print(search_procedures(args.query, top_k=args.top_k))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
