from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import relationship
from app.db.base import Base


class Role(Base):
    __tablename__ = "role"

    idrole      = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(20), nullable=False)
    status      = Column(String(20), nullable=False, default="Active")
    description = Column(Text, nullable=True)

    # Relationships
    users = relationship("User", back_populates="role")
