from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base


class Feedback(Base):
    __tablename__ = "feedback"

    idfeedback    = Column(Integer, primary_key=True, autoincrement=True)
    idchatsession = Column(UUID(as_uuid=True), ForeignKey("chatsession.idchatsession"), nullable=False)
    rating        = Column(Integer, nullable=True)
    comment       = Column(Text, nullable=True)
    createdat     = Column(DateTime, server_default=func.now())

    # Relationships
    chatsession = relationship("ChatSession", back_populates="feedbacks")
