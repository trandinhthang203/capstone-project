from pydantic import BaseModel
from typing import Optional


class RoleBase(BaseModel):
    name:        str
    description: Optional[str] = None


class RoleCreate(RoleBase):
    pass


class RoleUpdate(BaseModel):
    name:        Optional[str] = None
    status:      Optional[str] = None
    description: Optional[str] = None


class RoleResponse(RoleBase):
    idrole: int
    status: str

    model_config = {"from_attributes": True}
