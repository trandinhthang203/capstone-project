from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import DUMMY_PASSWORD_HASH, get_password_hash, verify_password
from app.db.session import get_db
from app.models.role import Role
from app.models.user import User
from app.schemas.user import PasswordChange, UserCreate, UserRegister, UserUpdate


class UserService:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    @staticmethod
    def _normalized_email(email: str) -> str:
        return email.strip().lower()

    def authenticate(self, email: str, password: str) -> User:
        user = self.db.query(User).filter(User.email == self._normalized_email(email)).first()
        password_matches = verify_password(
            password,
            user.password_hash if user else DUMMY_PASSWORD_HASH,
        )
        if not user or not user.is_active or not password_matches:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email hoặc mật khẩu không đúng",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user.last_login_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(user)
        return user

    def create_user(self, data: UserRegister | UserCreate, role_code: str = "user") -> User:
        email = self._normalized_email(data.email)
        if self.db.query(User.id).filter(User.email == email).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email đã được đăng ký")
        role = self.db.query(Role).filter(Role.code == role_code.lower()).first()
        if not role:
            raise HTTPException(status_code=500, detail="Role hệ thống chưa được cấu hình")
        user = User(role_id=role.id, full_name=data.full_name.strip(), email=email,
                    phone=data.phone, password_hash=get_password_hash(data.password))
        self.db.add(user)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email đã được đăng ký")
        self.db.refresh(user)
        return user

    def get_user_by_id(self, user_id: UUID) -> User:
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
        return user

    def get_user_by_email(self, email: str) -> User:
        user = self.db.query(User).filter(User.email == self._normalized_email(email)).first()
        if not user:
            raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
        return user

    def get_all_users(self, skip: int = 0, limit: int = 20) -> list[User]:
        return self.db.query(User).offset(skip).limit(min(limit, 100)).all()

    def update_user(self, user_id: UUID, data: UserUpdate) -> User:
        user = self.get_user_by_id(user_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(user, field, value)
        self.db.commit()
        self.db.refresh(user)
        return user

    def deactivate_user(self, user_id: UUID) -> User:
        user = self.get_user_by_id(user_id)
        if not user.is_active:
            raise HTTPException(status_code=400, detail="Tài khoản đã bị vô hiệu hóa")
        user.is_active = False
        user.token_version += 1
        self.db.commit()
        self.db.refresh(user)
        return user

    def change_password(self, user_id: UUID, data: PasswordChange) -> None:
        user = self.get_user_by_id(user_id)
        if not verify_password(data.current_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mật khẩu hiện tại không đúng",
            )
        if verify_password(data.new_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mật khẩu mới phải khác mật khẩu hiện tại",
            )
        user.password_hash = get_password_hash(data.new_password)
        user.token_version += 1
        self.db.commit()

    def get_profile_for_chatbot(self, user_id: UUID) -> dict:
        user = self.get_user_by_id(user_id)
        return {"full_name": user.full_name, "email": user.email, "phone": user.phone}
