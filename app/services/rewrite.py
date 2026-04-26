from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from datetime import datetime
from app.core.security import get_password_hash, verify_password


# ─── CREATE ───

def create_user(db: Session, data: UserCreate) -> User:
    if db.query(User).filter(User.citizenid == data.citizenid).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CCCD đã được đăng ký"
        )

    user = User(
        idrole      = data.idrole,
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
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ─── READ ─────

def get_user_by_id(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.iduser == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy người dùng"
        )
    return user


def get_user_by_citizenid(db: Session, citizenid: str) -> User | None:
    return db.query(User).filter(User.citizenid == citizenid).first()


def get_all_users(db: Session, skip: int = 0, limit: int = 20) -> list[User]:
    return db.query(User).offset(skip).limit(limit).all()


# ─── UPDATE ─────

def update_user(db: Session, user_id: int, data: UserUpdate) -> User:
    user = get_user_by_id(db, user_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


def update_last_login(db: Session, user_id: int) -> None:
    user = get_user_by_id(db, user_id)
    user.lastlogin = datetime.now()
    db.commit()


def change_password(db: Session, user_id: int, old_password: str, new_password: str) -> None:
    user = get_user_by_id(db, user_id)

    if not verify_password(old_password, user.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mật khẩu cũ không đúng"
        )

    user.password = get_password_hash(new_password)
    db.commit()


# ─── DELETE ────────

def deactivate_user(db: Session, user_id: int) -> User:
    user = get_user_by_id(db, user_id)

    if user.status == "Inactive":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tài khoản đã bị vô hiệu hóa trước đó"
        )

    user.status = "Inactive"
    db.commit()
    db.refresh(user)
    return user


# ─── AUTH ─────

def authenticate_user(db: Session, citizenid: str, password: str) -> User:
    user = get_user_by_citizenid(db, citizenid)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="CCCD hoặc mật khẩu không đúng"
        )

    if not verify_password(password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="CCCD hoặc mật khẩu không đúng"
        )

    if user.status != "Active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản đã bị vô hiệu hóa"
        )

    update_last_login(db, user.iduser)
    return user


# ─── CHATBOT ──────

def get_profile_for_chatbot(db: Session, user_id: int) -> dict:
    user = get_user_by_id(db, user_id)
    return {
        "fullname":    user.fullname,
        "dateofbirth": str(user.dateofbirth) if user.dateofbirth else None,
        "gender":      user.gender,
        "address":     user.address,
        "province":    user.province,
        "district":    user.district,
        "ward":        user.ward,
    }
