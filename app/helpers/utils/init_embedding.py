from dotenv import load_dotenv
from app.helpers.utils.logger import logging
import os

load_dotenv()

QDRANT_URL: str = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY: str = os.getenv("QDRANT_API_KEY", "")
COLLECTION_NAME: str = os.getenv("QDRANT_COLLECTION", "thu_tuc_hanh_chinh")

DENSE_MODEL_NAME: str = os.getenv(
    "QDRANT_DENSE_MODEL", "intfloat/multilingual-e5-large"
)
SPARSE_MODEL_NAME: str = "Qdrant/bm25"

# ------------------------------------------------------------------
# Lazy-load client + models (tránh khởi tạo khi import)
# ------------------------------------------------------------------

_client = None
_dense_model = None
_sparse_model = None


def _get_client():
    global _client
    if _client is None:
        from qdrant_client import QdrantClient  # type: ignore

        if QDRANT_URL:
            _client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None)
        else:
            # fallback: in-memory (chỉ dùng khi dev, không có collection thật)
            _client = QdrantClient(":memory:")
            logging.warning("[qdrant_retriever] QDRANT_URL chưa được cấu hình, dùng in-memory.")
    return _client


def _get_models():
    global _dense_model, _sparse_model
    if _dense_model is None or _sparse_model is None:
        from fastembed import TextEmbedding, SparseTextEmbedding  # type: ignore

        _dense_model = TextEmbedding(DENSE_MODEL_NAME)
        _sparse_model = SparseTextEmbedding(SPARSE_MODEL_NAME)
        logging.info("[qdrant_retriever] Models loaded: dense=%s sparse=%s", DENSE_MODEL_NAME, SPARSE_MODEL_NAME)
    return _dense_model, _sparse_model

