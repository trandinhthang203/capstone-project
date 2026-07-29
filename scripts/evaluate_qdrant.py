"""
scripts/evaluate_qdrant.py
--------------------------
Đánh giá chất lượng retrieval của Qdrant hybrid search trên tập evaluation.

Metrics tính toán:
    - Hit Rate    : Tỉ lệ query có ít nhất 1 kết quả đúng trong top-K
    - Recall@K    : Trung bình tỉ lệ doc đúng được tìm thấy
    - Precision@K : Trung bình tỉ lệ kết quả trả về là đúng
    - MRR         : Mean Reciprocal Rank

Định dạng file evaluation (.jsonl):
    {"query_id": "q001", "query_text": "...", "expected_doc_ids": ["1.001193"]}
    ...

Sử dụng:
    python -m scripts.evaluate_qdrant \\
        --dataset data/evaluation_dataset.jsonl \\
        --top-k 15 \\
        --only-errors

Biến môi trường (.env):
    QDRANT_URL, QDRANT_API_KEY, QDRANT_COLLECTION, QDRANT_DENSE_MODEL
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Đảm bảo import được các module trong project
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

QDRANT_URL: str = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY: str = os.getenv("QDRANT_API_KEY", "")
COLLECTION_NAME: str = os.getenv("QDRANT_COLLECTION", "thu_tuc_hanh_chinh")
DENSE_MODEL_NAME: str = os.getenv("QDRANT_DENSE_MODEL", "intfloat/multilingual-e5-large")
SPARSE_MODEL_NAME: str = "Qdrant/bm25"


# ── Load models & client (lazy, một lần) ────────────────────────────

_client = None
_dense_model = None
_sparse_model = None


def _init_resources():
    global _client, _dense_model, _sparse_model
    if _client is not None:
        return

    try:
        from qdrant_client import QdrantClient
        from fastembed import TextEmbedding, SparseTextEmbedding
    except ImportError as e:
        print(f"[ERROR] Thiếu thư viện: {e}")
        print("Cài đặt: pip install qdrant-client fastembed")
        sys.exit(1)

    if not QDRANT_URL:
        print("[ERROR] Chưa cấu hình QDRANT_URL trong .env")
        sys.exit(1)

    print(f"Đang load dense model: {DENSE_MODEL_NAME} ...")
    _dense_model = TextEmbedding(DENSE_MODEL_NAME)
    print(f"Đang load sparse model: {SPARSE_MODEL_NAME} ...")
    _sparse_model = SparseTextEmbedding(SPARSE_MODEL_NAME)

    _client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None)
    print(f"Kết nối Qdrant: {QDRANT_URL}, collection: {COLLECTION_NAME}\n")


# ── Dataset ─────────────────────────────────────────────────────────

def load_evaluation_set(dataset_path: Path) -> list[dict]:
    """
    Đọc file .jsonl với schema:
        {"query_id": str, "query_text": str, "expected_doc_ids": [str, ...]}
    """
    evaluation_set: list[dict] = []
    seen_ids: set[str] = set()

    with dataset_path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            item = json.loads(line)
            required = {"query_id", "query_text", "expected_doc_ids"}
            missing = required - set(item.keys())
            if missing:
                raise ValueError(f"Dòng {line_no} thiếu trường: {sorted(missing)}")

            if item["query_id"] in seen_ids:
                raise ValueError(f"Trùng query_id: {item['query_id']}")
            seen_ids.add(item["query_id"])

            if not isinstance(item["expected_doc_ids"], list) or not item["expected_doc_ids"]:
                raise ValueError(f"Dòng {line_no}: expected_doc_ids phải là list không rỗng")

            evaluation_set.append(item)

    if not evaluation_set:
        raise ValueError("Dataset rỗng.")
    return evaluation_set


# ── Search ──────────────────────────────────────────────────────────

def hybrid_search(query_text: str, top_k: int = 15) -> list[str]:
    """
    Thực hiện hybrid search và trả về danh sách `ma_so` của kết quả.
    """
    from qdrant_client import models as qm

    dense_vec = list(_dense_model.embed([query_text]))[0]
    sparse_vec = list(_sparse_model.embed([query_text]))[0]

    results = _client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            qm.Prefetch(
                query=dense_vec.tolist(),
                using="dense",
                limit=top_k * 2,
            ),
            qm.Prefetch(
                query=qm.SparseVector(
                    indices=sparse_vec.indices.tolist(),
                    values=sparse_vec.values.tolist(),
                ),
                using="bm25",
                limit=top_k * 2,
            ),
        ],
        query=qm.FusionQuery(fusion=qm.Fusion.RRF),
        limit=top_k,
    )

    retrieved_ids = []
    for point in results.points:
        ma_so = str(point.payload.get("ma_so", "")).strip()
        if ma_so:
            retrieved_ids.append(ma_so)
    return retrieved_ids


# ── Metrics ─────────────────────────────────────────────────────────

def calculate_metrics(retrieved_ids: list[str], expected_ids: list[str]) -> dict:
    expected_set = set(expected_ids)
    retrieved_set = set(retrieved_ids)

    num_relevant = len(expected_set & retrieved_set)
    hit = 1 if num_relevant > 0 else 0
    recall = num_relevant / len(expected_set) if expected_set else 0.0
    precision = num_relevant / len(retrieved_ids) if retrieved_ids else 0.0

    mrr = 0.0
    for rank, doc_id in enumerate(retrieved_ids, start=1):
        if doc_id in expected_set:
            mrr = 1.0 / rank
            break

    return {
        "hit": hit,
        "recall": recall,
        "precision": precision,
        "mrr": mrr,
    }


# ── Evaluate ────────────────────────────────────────────────────────

def evaluate_retrieval(
    eval_set: list[dict],
    top_k: int = 15,
    show_only_errors: bool = False,
    output_csv: str | None = None,
) -> None:
    total = len(eval_set)
    sums = {"hit": 0, "recall": 0.0, "precision": 0.0, "mrr": 0.0}
    error_count = 0
    rows_csv: list[dict] = []

    for item in eval_set:
        retrieved_ids = hybrid_search(item["query_text"], top_k=top_k)
        expected_ids = item["expected_doc_ids"]
        metrics = calculate_metrics(retrieved_ids, expected_ids)

        for key in sums:
            sums[key] += metrics[key]

        is_error = metrics["hit"] == 0
        if is_error:
            error_count += 1

        if not show_only_errors or is_error:
            tag = "✗ MISS" if is_error else "✓ HIT "
            print(
                f"[{tag}] {item['query_id']} | expected={expected_ids} | "
                f"retrieved={retrieved_ids[:5]}... | metrics={metrics}"
            )
            print(f"  Query: {item['query_text'][:100]}")

        rows_csv.append(
            {
                "query_id": item["query_id"],
                "query_text": item["query_text"],
                "expected_doc_ids": "|".join(expected_ids),
                "retrieved_top5": "|".join(retrieved_ids[:5]),
                **metrics,
            }
        )

    print("\n" + "=" * 60)
    print(f"Tổng số query         : {total}")
    print(f"Số query trượt (Hit=0): {error_count}")
    print(f"Hit Rate              : {sums['hit'] / total:.2%}")
    print(f"Recall@{top_k:<2}            : {sums['recall'] / total:.2%}")
    print(f"Precision@{top_k:<2}         : {sums['precision'] / total:.2%}")
    print(f"MRR                   : {sums['mrr'] / total:.4f}")
    print("=" * 60)

    if output_csv:
        import csv

        out_path = Path(output_csv)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows_csv[0].keys()))
            writer.writeheader()
            writer.writerows(rows_csv)
        print(f"\nĐã lưu chi tiết vào: {out_path.resolve()}")


# ── Main ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Đánh giá Qdrant hybrid retrieval trên tập evaluation"
    )
    parser.add_argument(
        "--dataset",
        default=str(ROOT / "data" / "evaluation_dataset.jsonl"),
        help="Đường dẫn file evaluation (.jsonl)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=15,
        help="Số kết quả retrieve (mặc định: 15)",
    )
    parser.add_argument(
        "--only-errors",
        action="store_true",
        help="Chỉ hiển thị các query trượt (Hit=0)",
    )
    parser.add_argument(
        "--output-csv",
        default=None,
        help="Lưu kết quả chi tiết ra file CSV (tuỳ chọn)",
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"[ERROR] Không tìm thấy file dataset: {dataset_path}")
        sys.exit(1)

    _init_resources()

    print(f"Đang load dataset: {dataset_path}")
    eval_set = load_evaluation_set(dataset_path)
    print(f"Tổng số query: {len(eval_set)}\n")

    evaluate_retrieval(
        eval_set=eval_set,
        top_k=args.top_k,
        show_only_errors=args.only_errors,
        output_csv=args.output_csv,
    )


if __name__ == "__main__":
    main()
