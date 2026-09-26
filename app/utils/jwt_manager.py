import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from jose import JWTError, jwt

from app.config.settings import settings


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp" : expires_at})

    return jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )

def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(
            token, 
            settings.JWT_SECRET_KEY, 
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError:
        return None
    
# Email-link tokens (verification, password reset) share one secret; the "type" claim stops a
# token of one kind being accepted as the other.
EmailTokenType = Literal["verify", "reset"]

def _create_email_token(user_id: uuid.UUID, token_type: EmailTokenType) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.EMAIL_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": str(user_id), "type": token_type, "exp": expires}
    return jwt.encode(to_encode, settings.JWT_EMAIL_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def create_email_verification_token(user_id: uuid.UUID) -> str:
    return _create_email_token(user_id, "verify")

def create_password_reset_token(user_id: uuid.UUID) -> str:
    return _create_email_token(user_id, "reset")

def decode_email_token(token: str, expected_type: EmailTokenType) -> uuid.UUID | None:
    """User id from a valid, unexpired email token of `expected_type`, otherwise None."""
    try:
        payload = jwt.decode(token, settings.JWT_EMAIL_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != expected_type:
            return None
        return uuid.UUID(payload["sub"])
    except (JWTError, KeyError, ValueError, TypeError):
        return None
