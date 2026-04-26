from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID


class ChatSessionCreate(BaseModel):
    iduser: int


class ChatSessionUpdate(BaseModel):
    status:    Optional[str] = None
    endeddate: Optional[datetime] = None


class ChatSessionResponse(BaseModel):
    idchatsession: UUID
    iduser:        int
    status:        str
    createddate:   Optional[datetime] = None
    endeddate:     Optional[datetime] = None

    model_config = {"from_attributes": True}


class ChatSessionClose(BaseModel):
    idchatsession: UUID
