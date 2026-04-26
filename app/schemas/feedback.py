from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime
from uuid import UUID


class FeedbackCreate(BaseModel):
    idchatsession: UUID
    rating:        Optional[int] = None
    comment:       Optional[str] = None

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, v):
        if v is not None and not (1 <= v <= 5):
            raise ValueError("Rating phải từ 1 đến 5")
        return v


class FeedbackResponse(BaseModel):
    idfeedback:    int
    idchatsession: UUID
    rating:        Optional[int] = None
    comment:       Optional[str] = None
    createdat:     Optional[datetime] = None

    model_config = {"from_attributes": True}
