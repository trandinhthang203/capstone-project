import uuid
from sqlalchemy import Column, Date, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base

class Basis(Base):
    __tablename__ = "basis"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    procedure_id = Column(UUID(as_uuid=True), ForeignKey("procedure.id", ondelete="CASCADE"), nullable=False)
    document_name = Column(Text, nullable=False)   # Tên văn bản pháp lý
    document_code = Column(String) 
    procedure = relationship("Procedure", back_populates="bases")
