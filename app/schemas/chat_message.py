from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID


class ChatMessageCreate(BaseModel):
    idchatsession: UUID
    msgcontent:    str
    isfromuser:    bool = True


class ChatMessageResponse(BaseModel):
    idchatmessage: int
    idchatsession: UUID
    msgcontent:    str
    isfromuser:    bool
    sentat:        Optional[datetime] = None

    model_config = {"from_attributes": True}


# Schema nhận tin nhắn từ user gửi lên API
class UserMessageRequest(BaseModel):
    idchatsession: UUID
    message:       str
