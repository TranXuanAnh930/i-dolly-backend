import uuid

from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.db.models.identity import Users
from app.deps.db import get_db
from app.utils.jwt_manager import decode_token

oauth_scheme = OAuth2PasswordBearer(tokenUrl="account/login")
# auto_error=False so a missing/absent Authorization header just yields
# token=None instead of a 401 — used by endpoints that are public but want
# to personalize the response for whoever happens to be logged in.
oauth_scheme_optional = OAuth2PasswordBearer(tokenUrl="account/login", auto_error=False)

def get_current_user(request:Request, token:str=Depends(oauth_scheme), db:Session=Depends(get_db)):
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user_id = uuid.UUID(payload.get("sub"))
    user = db.get(Users, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    request.state.user = user
    return user

def get_current_user_optional(request:Request, token:str|None=Depends(oauth_scheme_optional), db:Session=Depends(get_db)) -> Users|None:
    """Gate for public endpoints that personalize their response when the
    caller happens to be logged in (e.g. GET /concerts/{id}/detail flagging
    whether THIS viewer already has a ticket). Never raises — a missing,
    expired, or malformed token just resolves to None, same as a guest.
    """
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    user = db.get(Users, uuid.UUID(payload.get("sub")))
    if user:
        request.state.user = user
    return user

def require_admin(current_user:Users=Depends(get_current_user)) -> Users:
    """Gate for admin-only actions (managing categories, promoting users, etc.).
    Factored out per CLAUDE.md Section 5 item 8 — replaces the inline
    `if not current_user.is_admin: raise HTTPException(403, ...)` duplicated
    across products.py/category.py/order.py/user.py. Checks `role`, not
    `is_admin` — role is now the source of truth (is_admin is deprecated,
    kept in sync via the migration backfill only).
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

def require_manager_or_admin(current_user:Users=Depends(get_current_user)) -> Users:
    """Gate for actions a company manager can also do (CRUD on their own
    company's idols/groups/concerts/albums/singles/merchandise — see
    database-design.md Section 4's role table). Does NOT scope to the
    manager's own company_id — that's a query-level filter each service
    other mutating query already filters by user_id. This dependency only
    answers "is this role allowed to attempt the action at all."
    """
    if current_user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Manager or admin access required")
    return current_user