from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.cache.rate_limit import ip_key, rate_limit, user_key
from app.deps.auth import get_current_user
from app.deps.db import get_db
from app.schema.identity import UserCreate, UserOut
from app.services.identity.auth_service import AuthService

router = APIRouter(prefix="/account", tags=["Account"])

@router.post("/register", response_model=UserOut)
async def register(user:UserCreate, _:None=Depends(rate_limit(3,60,ip_key)), db:Session=Depends(get_db)):
    db_user = AuthService.create_user(db, user)
    if not db_user:
        raise HTTPException(status_code=400, detail="E-mail already registered")
    return db_user

@router.post("/login")
async def login(form_data:OAuth2PasswordRequestForm=Depends(), _:None=Depends(rate_limit(10,60,ip_key)), db:Session=Depends(get_db)):
    db_user = AuthService.authenticate_user(db, form_data.username, form_data.password)
    if not db_user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = AuthService.create_tokens(db, db_user)
    response = JSONResponse(content={"access_token": token["access_token"]})
    # samesite="none" (not "lax") — the frontend and this API are deployed
    # on different origins (e.g. Vercel + Render), which browsers treat as
    # cross-site. A Lax cookie is only sent on top-level navigations, never
    # on the XHR/fetch POST /account/refresh call the frontend makes after
    # a page reload — so it silently never reached this endpoint there,
    # refresh always failed, and every reload logged the fan out even
    # though their session was still otherwise valid. None requires
    # Secure, already set.
    response.set_cookie("refresh_token", token["refresh_token"], httponly=True, secure=True, samesite="none")
    return response

@router.post("/refresh")
async def refresh(request:Request, _:None=Depends(rate_limit(10,60,ip_key)), db:Session=Depends(get_db)):
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

@router.post("/verify-request")
async def send_verification_link(background_tasks:BackgroundTasks, user=Depends(get_current_user), _:None=Depends(rate_limit(5,60,user_key))):
    return AuthService.email_verification_process(background_tasks, user)

@router.get("/verify")
async def verify_email(token:str, _:None=Depends(rate_limit(5,60,ip_key)), db:Session=Depends(get_db)):
    result = AuthService.verify_email_token(db, token)
    if result is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    if result is False:
        raise HTTPException(status_code=401, detail="user not found or account already verified")
    return {"msg" : "Email verified successfully"}