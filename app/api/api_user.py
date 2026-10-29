from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, status

from app.core.deps import get_current_user
from app.core.permissions import require_roles
from app.models.user import User
from app.schemas.user import PasswordChange, UserCreate, UserResponse, UserUpdate
from app.services.user_service import UserService

router = APIRouter()


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("", response_model=UserResponse)
def update(
    data: UserUpdate = Body(...),
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(),
):
    return user_service.update_user(current_user.id, data)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    data: PasswordChange,
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(),
):
    user_service.change_password(current_user.id, data)


@router.post("/create", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create(
    data: UserCreate,
    user_service: UserService = Depends(),
    _: User = Depends(require_roles("admin")),
):
    return user_service.create_user(data, role_code=data.role_code)


@router.get("/all", response_model=list[UserResponse])
def get_all_users(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    user_service: UserService = Depends(),
    _: User = Depends(require_roles("admin")),
):
    return user_service.get_all_users(skip, limit)


@router.get("/{email}", response_model=UserResponse)
def get_user(
    email: str,
    user_service: UserService = Depends(),
    _: User = Depends(require_roles("admin")),
):
    return user_service.get_user_by_email(email)


@router.delete("/{user_id}", response_model=UserResponse)
def delete_user(
    user_id: UUID,
    user_service: UserService = Depends(),
    current_admin: User = Depends(require_roles("admin")),
):
    if current_admin.id == user_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Admin không thể tự vô hiệu hóa chính mình")
    return user_service.deactivate_user(user_id)
