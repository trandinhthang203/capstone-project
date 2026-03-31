from sqlalchemy import Column, Integer, Text, String, VARCHAR, Date, SmallInteger, ForeignKey
from sqlalchemy.orm import relationship
from app.db.base import Base

class Can_Cu_Phap_Ly(Base):
    __tablename__ = "can_cu_phap_ly"
    __table_args__ = {"schema": "rag"}

    ma_can_cu               = Column(Integer,       primary_key=True, autoincrement=True)
    so_ky_hieu              = Column(VARCHAR(100))
    trich_yeu               = Column(Text)
    ngay_ban_hanh           = Column(Date)
    co_quan_ban_hanh        = Column(VARCHAR(200))
    ma_thu_tuc              = Column(VARCHAR(50),   ForeignKey("rag.thu_tuc.ma_thu_tuc", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)

    thu_tuc                 = relationship("Thu_Tuc", back_populates="can_cu_phap_ly")