from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate, UserRegister
from datetime import datetime
from app.core.security import get_password_hash, verify_password
from fastapi import Depends
from app.db.session import get_db
from typing import Union
from app.helpers.utils.logger import logging
from typing import Optional

class UserService(object):
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

# ─── AUTH ───
    def authenticate(self, citizenid: str, password: str) -> Optional[User]:
        user = self.get_user_by_citizenid(citizenid)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sai mã định danh hoặc mật khẩu"
            )
        
        if user.status == "Inactive":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Tài khoán bị vô hiệu hóa"
            )
          
        if not verify_password(password, user.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sai mã định danh hoặc mật khẩu"
            )

        user.lastlogin = datetime.now()
        self.db.commit()
        
        return user

# ─── CREATE ───

    def create_user(self, data: Union[UserCreate, UserRegister], role: int = 2) -> User:
        if self.db.query(User).filter(User.citizenid == data.citizenid).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CCCD đã được đăng ký"
            )

        user = User(
            idrole      = role,
            fullname    = data.fullname,
            citizenid   = data.citizenid,
            password    = get_password_hash(data.password),
            phonenumber = data.phonenumber,
            dateofbirth = data.dateofbirth,
            gender      = data.gender,
            address     = data.address,
            province    = data.province,
            district    = data.district,
            ward        = data.ward,
            avatarurl   = data.avatarurl,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user


    # ─── READ ─────

    def get_user_by_id(self, user_id: int) -> User:
        user = self.db.query(User).filter(User.iduser == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy người dùng"
            )
        return user


    def get_user_by_citizenid(self, citizenid: str) -> User | None:
        user = self.db.query(User).filter(User.citizenid == citizenid).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy người dùng"
            )
        return user


    def get_all_users(self, skip: int = 0, limit: int = 20) -> list[User]:
        return self.db.query(User).offset(skip).limit(limit).all()


    # ─── UPDATE ─────

    def update_user(self, user_id: int, data: UserUpdate) -> User:
        user = self.get_user_by_id(user_id)

        update_data = data.model_dump(exclude_unset=True)
        print(data.model_dump(exclude_unset=True))
        for field, value in update_data.items():
            setattr(user, field, value)

        self.db.commit()
        self.db.refresh(user)
        return user


    def update_last_login(self, user_id: int) -> None:
        user = self.get_user_by_id(user_id)
        user.lastlogin = datetime.now()
        self.db.commit()


    def change_password(self, user_id: int, old_password: str, new_password: str) -> None:
        user = self.get_user_by_id(user_id)

        if not verify_password(old_password, user.password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mật khẩu cũ không đúng"
            )
        
        user.password = get_password_hash(new_password)
        self.db.commit()


    # ─── DELETE ────────

    def deactivate_user(self, user_id: int) -> User:
        user = self.get_user_by_id(user_id)

        if user.status == "Inactive":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tài khoản đã bị vô hiệu hóa trước đó"
            )

        user.status = "Inactive"
        self.db.commit()
        self.db.refresh(user)
        return user


    # ─── AUTH ─────

    # def authenticate_user(db: Session, citizenid: str, password: str) -> User:
    #     pass

    @staticmethod
    def get_profile_for_chatbot(self, user_id: int) -> dict:
        user = self.get_user_by_id(user_id)
        return {
            "fullname":    user.fullname,
            "dateofbirth": str(user.dateofbirth) if user.dateofbirth else None,
            "gender":      user.gender,
            "address":     user.address,
            "province":    user.province,
            "district":    user.district,
            "ward":        user.ward,
        }
