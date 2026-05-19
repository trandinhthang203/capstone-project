from pydantic import BaseModel
from typing import Optional, Any, Literal
from datetime import datetime
from uuid import UUID


class ChatMessageCreate(BaseModel):
    idchatsession: UUID
    msgcontent: str
    isfromuser: bool = True


class DynamicFormField(BaseModel):
    field_id: str
    label: str
    type: Literal["text", "textarea", "date", "number", "tel"] = "text"
    required: bool = True
    placeholder: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None


class DynamicFormPayload(BaseModel):
    kind: Literal["dynamic_form"] = "dynamic_form"
    request_id: str
    title: str
    description: Optional[str] = None
    submit_label: str = "Tiếp tục"
    fields: list[DynamicFormField]


class DynamicFormSubmitRequest(BaseModel):
    idchatsession: UUID
    request_id: str
    values: dict[str, Any]


class ChatMessageResponse(BaseModel):
    idchatmessage: int
    idchatsession: UUID
    msgcontent: str
    isfromuser: bool
    sentat: Optional[datetime] = None

    # NEW
    msgtype: str = "text"
    meta_data: Optional[dict] = None

    model_config = {"from_attributes": True}


# Schema nhận tin nhắn từ user gửi lên API
class UserMessageRequest(BaseModel):
    idchatsession: UUID
    message:       str
