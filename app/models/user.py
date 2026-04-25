from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.db.base import Base


class User(Base):
    __tablename__ = "User"

    iduser      = Column(Integer, primary_key=True, autoincrement=True)
    idrole      = Column(Integer, ForeignKey("role.idrole"), nullable=False)
    fullname    = Column(String(100), nullable=False)
    citizenid   = Column(String(12), nullable=False, unique=True)
    password    = Column(String(255), nullable=False)
    phonenumber = Column(String(15), nullable=True)
    dateofbirth = Column(Date, nullable=True)
    gender      = Column(String(10), default="Other")
    address     = Column(String(255), nullable=True)
    province    = Column(String(100), nullable=True)
    district    = Column(String(100), nullable=True)
    ward        = Column(String(100), nullable=True)
    avatarurl   = Column(String(500), nullable=True)
    status      = Column(String(20), nullable=False, default="Active")
    createdat   = Column(DateTime, server_default=func.now())
    lastlogin   = Column(DateTime, nullable=True)

    # Relationships
    role         = relationship("Role", back_populates="users")
    chatsessions = relationship("ChatSession", back_populates="user")
