"""
scripts/ingest_qdrant.py
------------------------
Ingest dữ liệu thủ tục hành chính từ PostgreSQL vào Qdrant (hybrid: dense + BM25).

Sử dụng:
    python -m scripts.ingest_qdrant [--batch-size 64] [--recreate]

Yêu cầu:
    pip install qdrant-client fastembed pandas

Biến môi trường (.env):
    QDRANT_URL          URL Qdrant Cloud hoặc self-hosted
    QDRANT_API_KEY      API key (tuỳ chọn, để trống nếu self-hosted không cần auth)
    QDRANT_COLLECTION   Tên collection (mặc định: thu_tuc_hanh_chinh)
    QDRANT_DENSE_MODEL  Model embed dense (mặc định: intfloat/multilingual-e5-large)
    SQL_DATABASE_URL    PostgreSQL connection string
"""

# from __future__ import annotations

# import argparse
# import os
# import sys
# from pathlib import Path

# # Đảm bảo import được các module trong project
# ROOT = Path(__file__).resolve().parent.parent
# sys.path.insert(0, str(ROOT))

# from dotenv import load_dotenv

# load_dotenv(ROOT / ".env")

# import numpy as np
# from sqlalchemy import select

# from app.db.session import get_db
# from app.helpers.utils.logger import logging
# from scripts.models.procedure import Thu_Tuc

# # ── Config ──────────────────────────────────────────────────────────
# QDRANT_URL: str = os.getenv("QDRANT_URL", "")
# QDRANT_API_KEY: str = os.getenv("QDRANT_API_KEY", "")
# COLLECTION_NAME: str = os.getenv("QDRANT_COLLECTION", "thu_tuc_hanh_chinh")
# DENSE_MODEL_NAME: str = os.getenv("QDRANT_DENSE_MODEL", "intfloat/multilingual-e5-large")
# DENSE_VECTOR_SIZE: int = 1024
# SPARSE_MODEL_NAME: str = "Qdrant/bm25"


# def build_text(proc: Thu_Tuc) -> str:
#     """Tạo chuỗi văn bản để embed từ một thủ tục."""
#     parts = [proc.ten_thu_tuc]
#     if proc.linh_vuc:
#         parts.append(proc.linh_vuc)
#     if proc.tu_khoa:
#         parts.append(proc.tu_khoa)
#     if proc.mo_ta:
#         parts.append(proc.mo_ta[:500])   # giới hạn độ dài mô tả
#     return " ".join(p.strip() for p in parts if p and p.strip())


# def build_payload(proc: Thu_Tuc) -> dict:
#     """Tạo payload metadata cho Qdrant point."""
#     return {
#         "ma_so": proc.ma_thu_tuc or "",
#         "ten_thu_tuc": proc.ten_thu_tuc or "",
#         "linh_vuc": proc.linh_vuc or "",
#         "co_quan_thuc_hien": proc.co_quan_thuc_hien or "",
#         "co_quan_co_tham_quyen": proc.co_quan_co_tham_quyen or "",
#         "cap_thuc_hien": proc.cap_thuc_hien or "",
#     }


# def main(batch_size: int = 64, recreate: bool = False):
#     # ── Import Qdrant + fastembed ──
#     try:
#         from qdrant_client import QdrantClient, models as qm
#         from fastembed import TextEmbedding, SparseTextEmbedding
#     except ImportError as e:
#         print(f"[ERROR] Thiếu thư viện: {e}")
#         print("Cài đặt: pip install qdrant-client fastembed")
#         sys.exit(1)

#     if not QDRANT_URL:
#         print("[ERROR] Chưa cấu hình QDRANT_URL trong .env")
#         sys.exit(1)

#     # ── Kết nối Qdrant ──
#     client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None)
#     print(f"Kết nối Qdrant tại: {QDRANT_URL}")
#     print(f"Collection: {COLLECTION_NAME}")

#     # ── Tạo / recreate collection ──
#     exists = client.collection_exists(COLLECTION_NAME)
#     if exists and recreate:
#         print(f"Đang xoá collection '{COLLECTION_NAME}'...")
#         client.delete_collection(COLLECTION_NAME)
#         exists = False

#     if not exists:
#         print(f"Tạo collection '{COLLECTION_NAME}'...")
#         client.create_collection(
#             collection_name=COLLECTION_NAME,
#             vectors_config={
#                 "dense": qm.VectorParams(
#                     size=DENSE_VECTOR_SIZE,
#                     distance=qm.Distance.COSINE,
#                 ),
#             },
#             sparse_vectors_config={
#                 "bm25": qm.SparseVectorParams(modifier=qm.Modifier.IDF),
#             },
#         )
#         # Tạo payload index cho filter
#         for field_name in ("linh_vuc", "co_quan_thuc_hien", "cap_thuc_hien"):
#             try:
#                 client.create_payload_index(
#                     collection_name=COLLECTION_NAME,
#                     field_name=field_name,
#                     field_schema=qm.PayloadSchemaType.KEYWORD,
#                 )
#             except Exception:
#                 pass
#     else:
#         print(f"Collection '{COLLECTION_NAME}' đã tồn tại, sẽ upsert.")

#     # ── Load dữ liệu từ PostgreSQL ──
#     print("Đang đọc dữ liệu từ PostgreSQL...")
#     db = next(get_db())
#     try:
#         procedures = db.execute(select(Thu_Tuc)).scalars().all()
#     finally:
#         db.close()

#     print(f"Đọc được {len(procedures)} thủ tục.")
#     if not procedures:
#         print("[WARN] Không có dữ liệu để ingest.")
#         return

#     # ── Load models ──
#     print(f"Đang load dense model: {DENSE_MODEL_NAME} ...")
#     dense_model = TextEmbedding(DENSE_MODEL_NAME)
#     print(f"Đang load sparse model: {SPARSE_MODEL_NAME} ...")
#     sparse_model = SparseTextEmbedding(SPARSE_MODEL_NAME)

#     # ── Chuẩn bị văn bản ──
#     texts = [build_text(p) for p in procedures]

#     # ── Embed dense ──
#     print("Đang sinh dense embeddings...")
#     dense_vecs = list(dense_model.embed(texts, batch_size=batch_size))
#     dense_vecs = [np.array(v) for v in dense_vecs]

#     # ── Embed sparse ──
#     print("Đang sinh sparse BM25 embeddings...")
#     sparse_vecs = list(sparse_model.embed(texts))

#     # ── Upsert vào Qdrant ──
#     total = len(procedures)
#     print(f"Đang upsert {total} điểm vào Qdrant (batch_size={batch_size})...")

#     for start in range(0, total, batch_size):
#         end = min(start + batch_size, total)
#         batch_procedures = procedures[start:end]
#         batch_dense = dense_vecs[start:end]
#         batch_sparse = sparse_vecs[start:end]

#         points = []
#         for i, (proc, dv, sv) in enumerate(zip(batch_procedures, batch_dense, batch_sparse)):
#             points.append(
#                 qm.PointStruct(
#                     id=start + i,
#                     vector={
#                         "dense": dv.tolist(),
#                         "bm25": qm.SparseVector(
#                             indices=sv.indices.tolist(),
#                             values=sv.values.tolist(),
#                         ),
#                     },
#                     payload=build_payload(proc),
#                 )
#             )

#         client.upsert(
#             collection_name=COLLECTION_NAME,
#             points=points,
#             wait=True,
#         )
#         print(f"  Đã upload {end}/{total}")

#     print(f"\nHoàn tất! Đã ingest {total} thủ tục vào collection '{COLLECTION_NAME}'.")

#     # ── Kiểm tra nhanh ──
#     info = client.get_collection(COLLECTION_NAME)
#     print(f"Collection info: vectors_count={info.vectors_count}, status={info.status}")


# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(description="Ingest thủ tục hành chính vào Qdrant")
#     parser.add_argument(
#         "--batch-size",
#         type=int,
#         default=64,
#         help="Số lượng điểm mỗi batch upsert (mặc định: 64)",
#     )
#     parser.add_argument(
#         "--recreate",
#         action="store_true",
#         help="Xoá và tạo lại collection trước khi ingest",
#     )
#     args = parser.parse_args()
#     main(batch_size=args.batch_size, recreate=args.recreate)


from fastembed import TextEmbedding
for m in TextEmbedding.list_supported_models():
    print(m["model"], m.get("size_in_GB"))