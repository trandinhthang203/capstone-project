from langchain_google_genai import GoogleGenerativeAIEmbeddings
from sqlalchemy import select
from app.db.session import get_db
from scripts.models.procedure import Thu_Tuc
from scripts.models.component import Thanh_Phan_Ho_So
from scripts.models.basis import Can_Cu_Phap_Ly
from scripts.models.method import Cach_Thuc_Thuc_Hien
from scripts.models.procedure_search_index import ProcedureSearchIndex
import os
from langchain_huggingface import HuggingFaceEmbeddings
from dotenv import load_dotenv

load_dotenv()

def build_search_text(proc: Thu_Tuc) -> str:
    parts = [
        proc.cap_thuc_hien,
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
    db = next(get_db())
    try:
        # embedder = HuggingFaceEmbeddings(
        #     model_name=os.getenv("EMBEDDING_MODEL"),
        #     model_kwargs={"trust_remote_code": True},
        #     encode_kwargs={"normalize_embeddings": True},
        # )

        procedures = db.execute(select(Thu_Tuc)).scalars().all()
        texts = [build_search_text(p) for p in procedures]
        # vectors = embedder.embed_documents(texts)

        for proc, text in zip(procedures, texts):
            db.merge(
                ProcedureSearchIndex(
                    ma_thu_tuc=proc.ma_thu_tuc,
                    ten_thu_tuc=proc.ten_thu_tuc,
                    search_text=text,
                    # embedding=vector,
                )
            )

        db.commit()
        print(f"Indexed {len(procedures)} procedures")
    finally:
        db.close()

def test_build_search_text():
    proc = Thu_Tuc(
        ma_thu_tuc="TT001",
        ten_thu_tuc="Cấp căn cước công dân",
        tu_khoa="căn cước, CCCD, cấp mới",
        linh_vuc="Hành chính",
        loai_thu_tuc="Thủ tục cấp mới",
        cap_thuc_hien="Cấp huyện",
        doi_tuong_thuc_hien="Công dân Việt Nam",
        co_quan_thuc_hien="Công an",
        yeu_cau_dieu_kien="Đủ 14 tuổi trở lên",
        mo_ta="Thủ tục cấp căn cước công dân lần đầu"
    )

    result = build_search_text(proc)
    print(result)

if __name__ == "__main__":
    main()
