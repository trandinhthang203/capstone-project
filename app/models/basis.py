import uuid
from sqlalchemy import Column, Date, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base

class Basis(Base):
    __tablename__ = "basis"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    procedure_id = Column(UUID(as_uuid=True), ForeignKey("procedure.id", ondelete="CASCADE"), nullable=False)
    order_index = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    document_number = Column(String)
    issued_date = Column(Date)
    content = Column(Text)
    source_url = Column(String)
    procedure = relationship("Procedure", back_populates="bases")
