import uuid

from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.db.models.identity import Users
from app.deps.db import get_db
from app.schema.identity import UserRole
from app.utils.jwt_manager import decode_token

oauth_scheme = OAuth2PasswordBearer(tokenUrl="account/login")
# auto_error=False: a missing token yields None instead of a 401, for public endpoints that
# personalize responses for logged-in users.
oauth_scheme_optional = OAuth2PasswordBearer(tokenUrl="account/login", auto_error=False)

def _user_from_token(token: str, db: Session) -> Users | None:
    """The token's user, or None if the token is invalid, has no valid `sub`, or the user is gone."""
    payload = decode_token(token)
    if not payload:
        return None
    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError):
        return None
    return db.get(Users, user_id)

def get_current_user(request:Request, token:str=Depends(oauth_scheme), db:Session=Depends(get_db)) -> Users:
    user = _user_from_token(token, db)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    request.state.user = user
    return user

def get_current_user_optional(request:Request, token:str|None=Depends(oauth_scheme_optional), db:Session=Depends(get_db)) -> Users|None:
    """Current user if a valid token is present, otherwise None (never raises)."""
    if not token:
        return None
    user = _user_from_token(token, db)
    if user:
        request.state.user = user
    return user

def require_admin(current_user:Users=Depends(get_current_user)) -> Users:
    """Require role == admin."""
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

def require_manager_or_admin(current_user:Users=Depends(get_current_user)) -> Users:
    """Require an admin or manager role. Company scoping is checked in each service."""
    if current_user.role not in (UserRole.admin, UserRole.manager):
        raise HTTPException(status_code=403, detail="Manager or admin access required")
    return current_user