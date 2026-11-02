import enum
import uuid
from sqlalchemy import Column, Date, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from sqlalchemy.orm import relationship
from app.db.base import Base

class Procedure(Base):
    """Chi tiết một phiên bản thủ tục (bảng `procedure`)."""
    __tablename__ = "procedure"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    procedure_id = Column(UUID(as_uuid=True), ForeignKey("procedures.id"), nullable=False, index=True)
    name = Column(Text, nullable=False)              # Tên thủ tục
    decision_number = Column(String, index=True)     # Số quyết định: 440/QĐ-BTC.NB
    level = Column(String)                           # Cấp thực hiện: Cấp bộ
    procedure_type = Column(String)                  # Loại thủ tục
    field = Column(String, index=True)               # Lĩnh vực: Quản lý nợ
    subject = Column(Text)                           # Đối tượng thực hiện
    competent_authority = Column(Text)               # Cơ quan có thẩm quyền
    reception_address = Column(Text)                 # Địa chỉ tiếp nhận HS
    delegated_authority = Column(Text)               # Cơ quan được ủy quyền
    coordinating_authority = Column(Text)            # Cơ quan phối hợp
    executing_authority = Column(Text)               # Cơ quan thực hiện
    steps = Column(Text)                             # Trình tự thực hiện
    requirements = Column(Text)                      # Yêu cầu, điều kiện thực hiện
    description = Column(Text)                       # Mô tả
    keywords = Column(ARRAY(String))                 # Từ khóa
    page_url = Column(String)      
    document_url = Column(String)  
    form_urls = Column(JSONB, nullable=False, server_default="[]")

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    procedure_group = relationship("ProcedureGroup", back_populates="versions")
    methods = relationship("Method", back_populates="procedure", cascade="all, delete-orphan")
    components = relationship("Component", back_populates="procedure", cascade="all, delete-orphan")
    bases = relationship("Basis", back_populates="procedure", cascade="all, delete-orphan")
