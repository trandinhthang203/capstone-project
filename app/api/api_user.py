from fastapi import APIRouter, Depends, Body, status
from app.schemas.user import UserResponse, UserUpdate, UserCreate
from app.helpers.utils.dependencies import get_current_user, require_roles
from app.models.user import User
from app.services.user_service import UserService
from app.helpers.utils.exception import CustomException
import sys

router = APIRouter()

# ------ Cần đăng nhập tài khoản------------
@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@router.patch("", response_model=UserResponse)
def update(
    data: UserUpdate = Body(...),
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends()
):
    try:
        return user_service.update_user(current_user.iduser, data)
    except Exception as e:
        raise CustomException(e, sys)


# ------------- Dành cho Admin-----------------
@router.post("/create", response_model=UserResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("Admin"))]
)
def create(create_data: UserCreate, user_service: UserService = Depends()):
    try:
        return user_service.create_user(create_data)
    except Exception as e:
        raise CustomException(e, sys)

@router.get("/all", response_model=list[UserResponse],
    dependencies=[Depends(require_roles("Admin"))]
)
def get_all_users(user_service: UserService = Depends()):
    return user_service.get_all_users()

@router.get("/{citizenid}", response_model=UserResponse,
    dependencies=[Depends(require_roles("Admin"))]
)
def get_user(citizenid: str, user_service: UserService = Depends()):
    return user_service.get_user_by_citizenid(citizenid)

@router.delete("/{user_id}", 
    dependencies=[Depends(require_roles("Admin"))]
)
def delete_user(user_id: int, user_service: UserService = Depends()):
    try:
        user = user_service.deactivate_user(user_id)
        return {
            "id" : user.iduser,
            "citizenid" : user.citizenid,
            "role": user.role.name,
            "status": user.status
        }
    except Exception as e:
        raise CustomException(e, sys)