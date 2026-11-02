import uuid
from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base

class Method(Base):
    __tablename__ = "method"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    procedure_id = Column(UUID(as_uuid=True), ForeignKey("procedure.id", ondelete="CASCADE"), nullable=False)
    method_type = Column(String)
    processing_time = Column(String)     # "Không quy định"
    fee = Column(String)                 # "Không có thông tin"
    description = Column(Text)
    procedure = relationship("Procedure", back_populates="methods")
