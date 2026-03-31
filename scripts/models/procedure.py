from sqlalchemy import Column, Text, String, VARCHAR
from sqlalchemy.orm import relationship
from app.db.base import Base

class Thu_Tuc(Base):
    __tablename__ = "thu_tuc"
    __table_args__ = {"schema": "rag"}  


    ma_thu_tuc              = Column(VARCHAR(50),   primary_key=True)
    link_tham_khao          = Column(VARCHAR(500))
    ten_thu_tuc             = Column(VARCHAR(255))
    cap_thuc_hien           = Column(VARCHAR(50))
    so_quyet_dinh           = Column(VARCHAR(100))
    loai_thu_tuc            = Column(VARCHAR(200))
    linh_vuc                = Column(VARCHAR(200))
    trinh_tu_thuc_hien      = Column(Text)
    doi_tuong_thuc_hien     = Column(VARCHAR(500))
    co_quan_thuc_hien       = Column(VARCHAR(200))
    co_quan_co_tham_quyen   = Column(VARCHAR(200))
    dia_chi_tiep_nhan_hs    = Column(VARCHAR(300))
    co_quan_duoc_uy_quyen   = Column(VARCHAR(200))
    co_quan_phoi_hop        = Column(VARCHAR(200))
    ket_qua_thuc_hien       = Column(Text)
    yeu_cau_dieu_kien       = Column(Text)
    tu_khoa                 = Column(VARCHAR(300))
    mo_ta                   = Column(Text)

    cach_thuc_thuc_hien     = relationship("Cach_Thuc_Thuc_Hien",   back_populates="thu_tuc", cascade="all, delete-orphan")
    thanh_phan_ho_so        = relationship("Thanh_Phan_Ho_So",      back_populates="thu_tuc", cascade="all, delete-orphan")
    can_cu_phap_ly          = relationship("Can_Cu_Phap_Ly",        back_populates="thu_tuc", cascade="all, delete-orphan")