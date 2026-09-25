from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.cache.rate_limit import ip_key, rate_limit, user_key
from app.db.models.identity import Users
from app.deps.auth import get_current_user
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.schema.common import MessageResponse
from app.schema.identity import UserCreate, UserOut
from app.services.identity.auth_service import AuthService

router = APIRouter(prefix="/account", tags=["Account"])

@router.post("/register", response_model=UserOut)
def register(user:UserCreate, _:None=Depends(rate_limit(3,60,ip_key)), db:Session=Depends(get_db)) -> Users:
    try:
        return AuthService.create_user(db, user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

@router.post("/login")
def login(form_data:OAuth2PasswordRequestForm=Depends(), _:None=Depends(rate_limit(10,60,ip_key)), db:Session=Depends(get_db)) -> JSONResponse:
    db_user = AuthService.authenticate_user(db, form_data.username, form_data.password)
    if not db_user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = AuthService.create_tokens(db, db_user)
    response = JSONResponse(content={"access_token": token["access_token"]})
    # SameSite=None (requires Secure) because the frontend is on a different site; a Lax cookie
    # wouldn't be sent with the frontend's fetch to POST /account/refresh.
    response.set_cookie("refresh_token", token["refresh_token"], httponly=True, secure=True, samesite="none")
    return response

@router.post("/refresh")
def refresh(request:Request, _:None=Depends(rate_limit(10,60,ip_key)), db:Session=Depends(get_db)) -> JSONResponse:
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing refresh token")
    user = AuthService.verify_refresh_token(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    new_token = AuthService.create_tokens(db, user)
    response = JSONResponse(content={"msg":"Token refreshed successfully", "access_token":new_token["access_token"]})
    response.set_cookie("refresh_token", new_token["refresh_token"], httponly=True, secure=True, samesite="none")
    return response

# Not used by the frontend.
@router.post("/verify-request", response_model=MessageResponse)
def send_verification_link(user:Users=Depends(get_current_user), _:None=Depends(rate_limit(5,60,user_key))) -> MessageResponse:
    AuthService.email_verification_process(user)
    return MessageResponse(msg="email verification link sent")

# Not used by the frontend.
@router.get("/verify", response_model=MessageResponse)
def verify_email(token:str, _:None=Depends(rate_limit(5,60,ip_key)), db:Session=Depends(get_db)) -> MessageResponse:
    result = AuthService.verify_email_token(db, token)
    if result is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    if result is False:
        raise HTTPException(status_code=401, detail="user not found or account already verified")
    return MessageResponse(msg="Email verified successfully")