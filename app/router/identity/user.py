from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.cache.rate_limit import ip_key, rate_limit, user_key
from app.db.models.identity import Users
from app.deps.auth import get_current_user, require_admin
from app.deps.db import get_db
from app.exception.common import ServiceError
from app.schema.common import MessageResponse
from app.schema.identity import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    MakeAdminRequest,
    ManagerCreate,
    SetPasswordRequest,
    UserOut,
)
from app.services.identity.user_service import UserService

router = APIRouter(prefix="/profile", tags=["Profile"])

@router.get("/me", response_model=UserOut)
def me(user:Users=Depends(get_current_user), _:None=Depends(rate_limit(60,60,user_key))) -> Users:
    return user

@router.put("/change-password", response_model=MessageResponse)
def change_password(payload:ChangePasswordRequest, user:Users=Depends(get_current_user), _:None=Depends(rate_limit(5,60,user_key)), db:Session=Depends(get_db)) -> MessageResponse:
    result = UserService.change_password_process(db, user, payload.old_password, payload.new_password)
    if not result:
        raise HTTPException(status_code=400, detail="Incorrect old password")
    return MessageResponse(msg="Password changed succesfully")

@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(payload:ForgotPasswordRequest, _:None=Depends(rate_limit(3,60,ip_key)), db:Session=Depends(get_db)) -> MessageResponse:
    # Same response whether or not the email exists, so accounts can't be enumerated.
    UserService.reset_password_process(db, payload.email)
    return MessageResponse(msg="If that email is registered, a password reset link has been sent")

@router.post("/set-password", response_model=MessageResponse)
def set_new_password(payload:SetPasswordRequest, _:None=Depends(rate_limit(5,60,ip_key)), db:Session=Depends(get_db)) -> MessageResponse:
    result = UserService.verify_rtoken(db, payload.token, payload.new_password)
    if result is False:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if result is None:
        raise HTTPException(status_code=404, detail="user not found")
    return MessageResponse(msg="password changed successfully")

# Not used by the frontend.
@router.post("/make-admin", response_model=MessageResponse)
def make_admin(payload:MakeAdminRequest, current_user:Users=Depends(require_admin), _:None=Depends(rate_limit(3,60,user_key)), db:Session=Depends(get_db)) -> MessageResponse:
    result = UserService.promote_admin(db, payload.user_id)
    if result is None:
        raise HTTPException(status_code=404, detail="user not found")
    if result is False:
        raise HTTPException(status_code=400, detail="user is already admin")
    return MessageResponse(msg=f"user {payload.user_id} promoted to admin successfully")

@router.post("/create-manager", response_model=UserOut)
def create_manager(payload:ManagerCreate, current_user:Users=Depends(require_admin), _:None=Depends(rate_limit(3,60,user_key)), db:Session=Depends(get_db)) -> Users:
    try:
        return UserService.create_manager_user(db, payload)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

@router.post("/logout", response_model=MessageResponse)
def logout(request:Request, db:Session=Depends(get_db)) -> JSONResponse:
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="not logged in")
    revoked = UserService.revoke_token(db, token)
    if not revoked:
        raise HTTPException(status_code=404, detail="refresh token not found")
    response = JSONResponse(content=MessageResponse(msg="Logged out successfully").model_dump())
    response.delete_cookie("refresh_token")
    return response

# Not used by the frontend.
@router.delete("/delete", response_model=MessageResponse)
def delete_existing_user(current_user:Users=Depends(get_current_user), db:Session=Depends(get_db)) -> MessageResponse:
    result = UserService.delete_user(db, current_user.id)
    if result is None:
        raise HTTPException(status_code=404, detail="user not found")
    return MessageResponse(msg=f"user {current_user.id} deleted successfully")