import secrets

import jwt
from jwt import InvalidTokenError
from passlib.context import CryptContext
from app.core.config import settings
from datetime import datetime, timedelta, timezone
from uuid import UUID

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
# Used when an account does not exist so login attempts take comparable time.
DUMMY_PASSWORD_HASH = pwd_context.hash("not-a-real-password-123")

def create_access_token(user_id: UUID | str, token_version: int = 0) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(
        seconds=settings.ACCESS_TOKEN_EXPIRE_SECONDS
    )
    to_encode = {
        "sub": str(user_id),
        "type": "access",
        "ver": token_version,
        "jti": secrets.token_urlsafe(16),
        "iat": now,
        "exp": expire,
    }
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.SECURITY_ALGORITHM)
    return encoded_jwt


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except (ValueError, TypeError):
        return False


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def decode_token(token: str) -> dict:
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.SECURITY_ALGORITHM],
        options={"require": ["sub", "type", "ver", "jti", "iat", "exp"]},
    )
    if payload.get("type") != "access":
        raise InvalidTokenError("Invalid token type")
    return payload
