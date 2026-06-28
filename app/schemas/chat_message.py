from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel


class ChatMessageCreate(BaseModel):
    idchatsession: UUID
    msgcontent: str
    isfromuser: bool = True


class DynamicFormOption(BaseModel):
    value: str
    label: str


class DynamicFormField(BaseModel):
    field_id: str
    label: str
    type: Literal["text", "textarea", "date", "number", "tel", "select"] = "text"
    required: bool = True
    placeholder: Optional[str] = None
    value: Optional[str] = None
    prefill_source: Optional[str] = None
    prefill_key: Optional[str] = None
    options: Optional[list[DynamicFormOption]] = None
    x: Optional[float] = None
    y: Optional[float] = None
    page: Optional[int] = 0


class DynamicFormPayload(BaseModel):
    kind: Literal["dynamic_form"] = "dynamic_form"
    request_id: str
    title: str
    description: Optional[str] = None
    submit_label: str = "Tiếp tục"
    pdf_path: Optional[str] = None
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
    msgtype: str = "text"
    meta_data: Optional[dict] = None

    model_config = {"from_attributes": True}


class UserMessageRequest(BaseModel):
    idchatsession: UUID
    message: str
