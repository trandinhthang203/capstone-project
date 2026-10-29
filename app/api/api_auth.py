from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.security import create_access_token
from app.schemas.user import UserLoginResponse, UserRegister, UserResponse
from app.services.user_service import UserService

router = APIRouter()


@router.post("/login", response_model=UserLoginResponse)
def login(
    credentials: OAuth2PasswordRequestForm = Depends(),
    user_service: UserService = Depends(),
):
    user = user_service.authenticate(credentials.username, credentials.password)
    return UserLoginResponse(
        access_token=create_access_token(user.id, user.token_version),
        user=user,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(data: UserRegister, user_service: UserService = Depends()):
    # Client không được tự chọn role khi đăng ký.
    return user_service.create_user(data, role_code="user")
