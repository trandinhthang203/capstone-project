from sqlalchemy import Column, Integer, Text, String, VARCHAR, ForeignKey
from sqlalchemy.orm import relationship
from app.db.base import Base


class Thanh_Phan_Ho_So(Base):
    __tablename__ = "thanh_phan_ho_so"
    __table_args__ = {"schema": "rag"}

    ma_thanh_phan           = Column(Integer,       primary_key=True, autoincrement=True)
    truong_hop              = Column(VARCHAR(300))
    loai_giay_to            = Column(Text)
    mau_don_to_khai         = Column(VARCHAR(500))
    so_luong                = Column(VARCHAR(50))
    ma_thu_tuc              = Column(VARCHAR(50),   ForeignKey("rag.thu_tuc.ma_thu_tuc", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)

    thu_tuc                 = relationship("Thu_Tuc", back_populates="thanh_phan_ho_so")