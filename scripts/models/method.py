from sqlalchemy import Column, Integer, Text, String, VARCHAR, ForeignKey
from sqlalchemy.orm import relationship
from app.db.base import Base

class Cach_Thuc_Thuc_Hien(Base):
    __tablename__ = "cach_thuc_thuc_hien"
    __table_args__ = {"schema": "rag"}

    ma_cach_thuc            = Column(Integer,       primary_key=True, autoincrement=True)
    hinh_thuc_nop           = Column(VARCHAR(20))
    thoi_han_giai_quyet     = Column(VARCHAR(50))
    phi_le_phi              = Column(Text)
    mo_ta                   = Column(Text)
    ma_thu_tuc              = Column(VARCHAR(50),   ForeignKey("rag.thu_tuc.ma_thu_tuc", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)

    thu_tuc                 = relationship("Thu_Tuc", back_populates="cach_thuc_thuc_hien")