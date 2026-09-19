from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.cache.rate_limit import ip_key, rate_limit, user_key
from app.db.models.identity import Users
from app.deps.auth import get_current_user, require_admin
from app.deps.db import get_db
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
async def me(user:Users=Depends(get_current_user), _:None=Depends(rate_limit(10,60,user_key))) -> Users:
    return user

@router.put("/change-password")
async def change_password(payload:ChangePasswordRequest, user:Users=Depends(get_current_user), _:None=Depends(rate_limit(5,60,user_key)), db:Session=Depends(get_db)) -> dict[str, str]:
    result = UserService.change_password_process(db, user, payload.old_password, payload.new_password)
    if not result:
        raise HTTPException(status_code=400, detail="Incorrect old password")
    return {"msg" : "Password changed succesfully"}

@router.post("/forgot-password")
async def forgot_password(payload:ForgotPasswordRequest, background_tasks:BackgroundTasks, _:None=Depends(rate_limit(3,60,ip_key)), db:Session=Depends(get_db)) -> dict[str, str]:
    # Always the same generic response, whether or not the email is
    # registered — reset_password_process no-ops silently for an unknown
    # email, so this endpoint can't be used to enumerate accounts.
    UserService.reset_password_process(db, payload.email, background_tasks)
    return {"msg" : "If that email is registered, a reset token has been sent"}

@router.post("/set-password")
async def set_new_password(payload:SetPasswordRequest, _:None=Depends(rate_limit(5,60,ip_key)), db:Session=Depends(get_db)) -> dict[str, str]:
    result = UserService.verify_rtoken(db, payload.token, payload.new_password)
    if result is False:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if result is None:
        raise HTTPException(status_code=404, detail="user not found")
    return {"msg" : "password changed successfully"}

@router.post("/make-admin")
async def make_admin(payload:MakeAdminRequest, current_user:Users=Depends(require_admin), _:None=Depends(rate_limit(3,60,user_key)), db:Session=Depends(get_db)) -> dict[str, str]:
    result = UserService.promote_admin(db, payload.user_id)
    if result is None:
        raise HTTPException(status_code=404, detail="user not found")
    if result is False:
        raise HTTPException(status_code=400, detail="user is already admin")
    return {"msg" : f"user {payload.user_id} promoted to admin successfully"}

@router.post("/create-manager", response_model=UserOut)
async def create_manager(payload:ManagerCreate, current_user:Users=Depends(require_admin), _:None=Depends(rate_limit(3,60,user_key)), db:Session=Depends(get_db)) -> Users:
    result = UserService.create_manager_user(db, payload)
    if result == "email_taken":
        raise HTTPException(status_code=400, detail="E-mail already registered")
    if result == "company_not_found":
        raise HTTPException(status_code=404, detail="Management company not found")
    return result

@router.post("/logout")
async def logout(request:Request, db:Session=Depends(get_db)) -> JSONResponse:
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="not logged in")
    revoked = UserService.revoke_token(db, token)
    if not revoked:
        raise HTTPException(status_code=404, detail="refresh token not found")
    response = JSONResponse(content={"detail" : "Logged out successfully"})
    response.delete_cookie("refresh_token")
    return response

@router.delete("/delete")
async def delete_existing_user(current_user:Users=Depends(get_current_user), db:Session=Depends(get_db)) -> dict[str, str]:
    result = UserService.delete_user(db, current_user.id)
    if result is None:
        raise HTTPException(status_code=404, detail="user not found")
    return {"msg" : f"user {current_user.id} deleted successfully"}