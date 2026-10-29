import uuid
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base

class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False)
    full_name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    phone = Column(String)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    token_version = Column(Integer, nullable=False, default=0, server_default="0")
    last_login_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    role = relationship("Role", back_populates="users")
    procedures = relationship("ProcedureGroup", back_populates="user")
    sessions = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")
