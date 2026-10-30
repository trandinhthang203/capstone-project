import enum
import uuid
from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base

class ProcedureGroupStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"

class ProcedureGroup(Base):
    """Danh mục/nhóm thủ tục (bảng `procedures`)."""
    __tablename__ = "procedures"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    code = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)
    issuing_agency = Column(String)
    implementing_agency = Column(String)
    domain = Column(String)
    status = Column(
        Enum(
            ProcedureGroupStatus,
            name="procedure_group_status",
            values_callable=lambda enum_class: [item.value for item in enum_class],
        ),
        nullable=False,
        default=ProcedureGroupStatus.DRAFT,
    )
    page_url = Column(String)      
    document_url = Column(String)  
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    user = relationship("User", back_populates="procedures")
    versions = relationship("Procedure", back_populates="procedure_group", cascade="all, delete-orphan")
