from sqlalchemy import Column, Text, String, ForeignKey, DateTime, Computed, func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.db.base import Base


class ProcedureSearchIndex(Base):
    __tablename__ = "procedure_search_index"
    __table_args__ = {"schema": "rag"}

    ma_thu_tuc = Column(String(50), ForeignKey("rag.thu_tuc.ma_thu_tuc", ondelete="CASCADE"), primary_key=True)
    ten_thu_tuc = Column(Text, nullable=False)
    search_text = Column(Text, nullable=False)
    search_tsv = Column(
        TSVECTOR,
        Computed(
            """
            setweight(to_tsvector('simple_unaccent', coalesce(ten_thu_tuc, '')), 'A') ||
            setweight(to_tsvector('simple_unaccent', coalesce(search_text, '')), 'B')
            """,
            persisted=True
        ),
        nullable=False,
    )
    embedding = Column(Vector(384), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    thu_tuc = relationship("Thu_Tuc", backref="search_index", uselist=False)
