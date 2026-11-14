import hashlib
import hmac
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

def _create_email_token(user_id: uuid.UUID, token_type: EmailTokenType, **claims: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.EMAIL_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": str(user_id), "type": token_type, "exp": expires, **claims}
    return jwt.encode(to_encode, settings.JWT_EMAIL_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def _decode_email_payload(token: str, expected_type: EmailTokenType) -> tuple[uuid.UUID, dict] | None:
    try:
        payload = jwt.decode(token, settings.JWT_EMAIL_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != expected_type:
            return None
        return uuid.UUID(payload["sub"]), payload
    except (JWTError, KeyError, ValueError, TypeError):
        return None

def create_email_verification_token(user_id: uuid.UUID) -> str:
    return _create_email_token(user_id, "verify")

def decode_email_token(token: str, expected_type: EmailTokenType) -> uuid.UUID | None:
    """User id from a valid, unexpired email token of `expected_type`, otherwise None."""
    decoded = _decode_email_payload(token, expected_type)
    return decoded[0] if decoded else None

# A reset token carries a fingerprint of the password hash it was issued against. Setting a new
# password changes the hash, so the link stops working once it has been used, and any link
# issued before another password change does too. The token is signed, so the fingerprint can't
# be forged; it's a truncated SHA-256, so the bcrypt hash itself never appears in the link.

def password_fingerprint(hashed_password: str) -> str:
    return hashlib.sha256(hashed_password.encode()).hexdigest()[:32]

def create_password_reset_token(user_id: uuid.UUID, hashed_password: str) -> str:
    return _create_email_token(user_id, "reset", pwd=password_fingerprint(hashed_password))

def decode_password_reset_token(token: str) -> tuple[uuid.UUID, str] | None:
    """(user id, password fingerprint) from a valid, unexpired reset token, otherwise None. A
    token without a fingerprint (issued before fingerprints existed) is invalid."""
    decoded = _decode_email_payload(token, "reset")
    if not decoded or not isinstance(decoded[1].get("pwd"), str):
        return None
    return decoded[0], decoded[1]["pwd"]

def password_fingerprint_matches(fingerprint: str, hashed_password: str) -> bool:
    return hmac.compare_digest(fingerprint, password_fingerprint(hashed_password))
