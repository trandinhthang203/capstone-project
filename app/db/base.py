from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Được migrations/env.py import để đăng ký toàn bộ model vào metadata.
from app.models import (  # noqa: E402,F401
    Basis, ChatMessage, ChatSession, Component, Method,
    Procedure, ProcedureGroup, Role, User,
)
