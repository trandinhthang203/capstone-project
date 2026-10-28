import uuid
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base

class Component(Base):
    __tablename__ = "component"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    procedure_id = Column(UUID(as_uuid=True), ForeignKey("procedure.id", ondelete="CASCADE"), nullable=False)
    order_index = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    is_required = Column(Boolean, nullable=False, default=False, server_default="false")
    procedure = relationship("Procedure", back_populates="components")
