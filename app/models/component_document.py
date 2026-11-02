import uuid
from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base

class ComponentDocument(Base):
    """Một dòng giấy tờ trong bảng của một trường hợp."""
    __tablename__ = "component_document"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    component_id = Column(
        UUID(as_uuid=True), ForeignKey("component.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name = Column(Text, nullable=False)   
    form_name = Column(String)           
    form_url = Column(String)            
    quantity = Column(String)           

    component = relationship("Component", back_populates="documents")