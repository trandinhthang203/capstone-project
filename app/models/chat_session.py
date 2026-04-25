import uuid
from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base


class ChatSession(Base):
    __tablename__ = "chatsession"

    idchatsession = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    iduser        = Column(Integer, ForeignKey("User.iduser"), nullable=False)
    status        = Column(String(20), nullable=False, default="Open")
    createddate   = Column(DateTime, server_default=func.now())
    endeddate     = Column(DateTime, nullable=True)

    # Relationships
    user         = relationship("User", back_populates="chatsessions")
    chatmessages = relationship("ChatMessage", back_populates="chatsession")
    feedbacks    = relationship("Feedback", back_populates="chatsession")
