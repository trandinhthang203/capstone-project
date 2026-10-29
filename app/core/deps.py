from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.core.security import decode_token
from jwt import InvalidTokenError
from app.db.session import get_db
from app.models.user import User
from app.core.config import settings
from uuid import UUID

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_PREFIX}/auth/login")

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        user_id = UUID(payload["sub"])
        token_version = payload["ver"]
        if not isinstance(token_version, int):
            raise InvalidTokenError("Invalid token version")
    except (InvalidTokenError, KeyError, TypeError, ValueError):
        raise credentials_exception from None

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active or user.token_version != token_version:
        raise credentials_exception
    return user
