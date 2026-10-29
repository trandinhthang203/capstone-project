"""Bootstrap the first administrator account from a trusted server terminal."""

import argparse
from getpass import getpass

from sqlalchemy.exc import IntegrityError

from app.core.security import get_password_hash
from app.db.session import SessionLocal
from app.models.role import Role
from app.models.user import User
from app.schemas.user import UserRegister


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the initial admin account")
    parser.add_argument("--email", required=True, help="Administrator email")
    parser.add_argument("--name", required=True, help="Administrator full name")
    parser.add_argument("--phone", help="Administrator phone number")
    return parser.parse_args()


def read_password() -> str:
    password = getpass("Mật khẩu: ")
    confirmation = getpass("Nhập lại mật khẩu: ")
    if password != confirmation:
        raise ValueError("Mật khẩu xác nhận không khớp")
    return password


def create_admin(email: str, name: str, phone: str | None, password: str) -> User:
    # Reuse the public registration validation, including bcrypt's 72-byte limit.
    data = UserRegister(
        full_name=name,
        email=email,
        phone=phone,
        password=password,
    )

    with SessionLocal() as db:
        existing = db.query(User).filter(User.email == data.email).first()
        if existing:
            # Never silently promote an existing account from a bootstrap command.
            raise ValueError(f"Email {data.email} đã tồn tại")

        admin_role = db.query(Role).filter(Role.code == "admin").first()
        if not admin_role:
            raise RuntimeError("Chưa có role admin; hãy chạy 'alembic upgrade head' trước")

        admin = User(
            role_id=admin_role.id,
            full_name=data.full_name,
            email=data.email,
            phone=data.phone,
            password_hash=get_password_hash(data.password),
        )
        db.add(admin)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ValueError(f"Email {data.email} đã tồn tại") from exc
        db.refresh(admin)
        return admin


def main() -> int:
    args = parse_args()
    try:
        admin = create_admin(
            email=args.email,
            name=args.name,
            phone=args.phone,
            password=read_password(),
        )
    except (RuntimeError, ValueError) as exc:
        print(f"Không thể tạo admin: {exc}")
        return 1

    print(f"Đã tạo admin: {admin.email} ({admin.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
