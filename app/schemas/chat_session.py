from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ChatSessionCreate(BaseModel):
    user_id: UUID
    title: str | None = None


class ChatSessionUpdate(BaseModel):
    title: str | None = None


class ChatSessionResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ChatSessionClose(BaseModel):
    id: UUID
