from sqlalchemy import Column, Integer, Text, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base


class ChatMessage(Base):
    __tablename__ = "chatmessage"

    idchatmessage = Column(Integer, primary_key=True, autoincrement=True)
    idchatsession = Column(UUID(as_uuid=True), ForeignKey("chatsession.idchatsession"), nullable=False)
    msgcontent    = Column(Text, nullable=False)
    isfromuser    = Column(Boolean, default=True)
    sentat        = Column(DateTime, server_default=func.now())

    # Relationships
    chatsession = relationship("ChatSession", back_populates="chatmessages")
