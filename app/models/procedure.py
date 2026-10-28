import enum
import uuid
from sqlalchemy import Column, Date, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base

class ProcedureStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"

class Procedure(Base):
    """Chi tiết một phiên bản thủ tục (bảng `procedure`)."""
    __tablename__ = "procedure"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    procedure_id = Column(UUID(as_uuid=True), ForeignKey("procedures.id"), nullable=False, index=True)
    version = Column(String, nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    summary = Column(Text)
    fee = Column(String)
    processing_time = Column(String)
    jurisdiction = Column(String)
    status = Column(
        Enum(
            ProcedureStatus,
            name="procedure_status",
            values_callable=lambda enum_class: [item.value for item in enum_class],
        ),
        nullable=False,
        default=ProcedureStatus.DRAFT,
    )
    content_hash = Column(String)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    procedure_group = relationship("ProcedureGroup", back_populates="versions")
    methods = relationship("Method", back_populates="procedure", cascade="all, delete-orphan")
    components = relationship("Component", back_populates="procedure", cascade="all, delete-orphan")
    bases = relationship("Basis", back_populates="procedure", cascade="all, delete-orphan")
