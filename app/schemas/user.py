from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import date, datetime


class UserBase(BaseModel):
    fullname:    str
    citizenid:   str
    phonenumber: Optional[str] = None
    dateofbirth: Optional[date] = None
    gender:      Optional[str] = "Other"
    address:     Optional[str] = None
    province:    Optional[str] = None
    district:    Optional[str] = None
    ward:        Optional[str] = None
    avatarurl:   Optional[str] = None

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, v):
        if v not in ("Male", "Female", "Other"):
            raise ValueError("gender phải là Male, Female hoặc Other")
        return v

    @field_validator("citizenid")
    @classmethod
    def validate_citizenid(cls, v):
        if not v.isdigit() or len(v) != 12:
            raise ValueError("CCCD phải gồm đúng 12 chữ số")
        return v


class UserCreate(UserBase):
    idrole:   int
    password: str


class UserUpdate(BaseModel):
    fullname:    Optional[str] = None
    phonenumber: Optional[str] = None
    dateofbirth: Optional[date] = None
    gender:      Optional[str] = None
    address:     Optional[str] = None
    province:    Optional[str] = None
    district:    Optional[str] = None
    ward:        Optional[str] = None
    avatarurl:   Optional[str] = None
    status:      Optional[str] = None


class UserResponse(UserBase):
    iduser:    int
    idrole:    int
    status:    str
    createdat: Optional[datetime] = None
    lastlogin: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserLogin(BaseModel):
    citizenid: str
    password:  str


class UserLoginResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user:         UserResponse
