from fastapi import APIRouter
from app.schemas.user import *
from app.services.user_service import UserService
from fastapi import Depends
from app.core.security import create_access_token
from fastapi.security import OAuth2PasswordRequestForm
from app.helpers.utils.exception import CustomException
import sys

router = APIRouter()

@router.post("/login", response_model=UserLoginResponse)
def login(user_login : OAuth2PasswordRequestForm = Depends(), user_service : UserService = Depends()):
    try:
        user = user_service.authenticate(user_login.username, user_login.password)
        return UserLoginResponse(
            access_token=create_access_token(user.iduser),
            user = user
        )
    except Exception as e:
        raise CustomException(e, sys)


@router.post("/register", response_model=UserResponse)
def register(register_data: UserRegister, user_service : UserService = Depends()):
    try:
        register_user = user_service.create_user(register_data)
        return register_user
    except Exception as e:
        raise CustomException(e, sys)