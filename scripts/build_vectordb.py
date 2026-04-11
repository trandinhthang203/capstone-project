from langchain_google_genai import GoogleGenerativeAIEmbeddings
from sqlalchemy import select
from app.db.session import SessionLocal
from scripts.models.procedure import Thu_Tuc
from scripts.models.procedure_search_index import ProcedureSearchIndex
import os


EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "models/text-embedding-004")


def build_search_text(proc: Thu_Tuc) -> str:
    parts = [
        proc.ten_thu_tuc,
        proc.tu_khoa,
        proc.linh_vuc,
        proc.loai_thu_tuc,
        proc.doi_tuong_thuc_hien,
        proc.co_quan_thuc_hien,
        proc.yeu_cau_dieu_kien,
        proc.mo_ta,
    ]
    return "\n".join([p.strip() for p in parts if p and p.strip()])


def main():
    db = SessionLocal()
    try:
        embedder = GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL,
            google_api_key=os.getenv("GEMINI_API_KEY"),
        )

        procedures = db.execute(select(Thu_Tuc)).scalars().all()
        texts = [build_search_text(p) for p in procedures]
        vectors = embedder.embed_documents(texts)  # batch => nhanh hơn loop từng item

        for proc, text, vector in zip(procedures, texts, vectors):
            db.merge(
                ProcedureSearchIndex(
                    ma_thu_tuc=proc.ma_thu_tuc,
                    ten_thu_tuc=proc.ten_thu_tuc,
                    search_text=text,
                    embedding=vector,
                )
            )

        db.commit()
        print(f"Indexed {len(procedures)} procedures")
    finally:
        db.close()


if __name__ == "__main__":
    main()
