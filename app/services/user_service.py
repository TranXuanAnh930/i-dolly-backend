import uuid
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session
from app.db.models.user import Users
from app.db.models.refresh_token import RefreshToken
from app.db.models.management_company import ManagementCompany
from app.schema.user import ManagerCreate
from app.utils.email_sender import send_email
from app.utils.hashing import hash_password, verify_password
from app.utils.jwt_manager import create_password_reset_token, verify_rtoken_and_get_user_id

def change_password_process(db: Session, user:Users, old_password: str, new_password: str):
    password_verification = verify_password(old_password, user.hashed_password)
    if not password_verification:
        return None
    user.hashed_password = hash_password(new_password)
    db.commit()
    db.refresh(user)
    return True

def reset_password_process(db: Session, email: str, background_tasks:BackgroundTasks):
    # Always returns True, whether or not the email is registered — the
    # router gives the same generic response either way, so this endpoint
    # can't be used to enumerate which emails have an account. Only the
    # matched-user branch actually queues anything.
    user = db.query(Users).filter(Users.email == email).first()
    if user:
        token = create_password_reset_token(user.id)
        email_body = f"""
            Hi {user.email},
            This is I-Dolly.
            Thank you for using our service. We received a request to reset your password. If you did not make this request, please ignore this email.
            Your password reset token is:

            {token}

            This token is valid for only 15 minutes. Please use it to reset your password. If you have any questions, please contact our support team.

        """
        background_tasks.add_task(send_email, user.email, "Reset password", email_body)
    return True

def verify_rtoken(db: Session, token: str, new_password: str):
    user_id = verify_rtoken_and_get_user_id(token, "reset")
    if not user_id:
        return False
    user = db.query(Users).filter(Users.id == user_id).first()
    if not user:
        return None
    user.hashed_password = hash_password(new_password)
    # Revoke every existing refresh token, same as a fresh login (create_tokens)
    # — otherwise a session an attacker already held survives the very reset
    # meant to lock them out.
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user.id,
        RefreshToken.revoked == False
    ).update({"revoked": True})
    db.commit()
    db.refresh(user)
    return True

def promote_admin(db: Session, user_id: uuid.UUID):
    user = db.get(Users, user_id)
    if not user:
        return None
    if user.is_admin:
        return False
    user.is_admin = True
    db.commit()
    db.refresh(user)
    return True

def create_manager_user(db: Session, data: ManagerCreate):
    """Admin-only counterpart to self-register — creates a brand new
    role='manager' account tied to a company in one call, rather than
    promoting an already-registered fan (which /make-admin does for admins,
    but with no company concept). Returns a short string sentinel for the
    two distinct failure modes, matching this file's other multi-way-failure
    functions (architecture.md SS2)."""
    if db.query(Users).filter(Users.email == data.email).first():
        return "email_taken"
    if not db.get(ManagementCompany, data.company_id):
        return "company_not_found"
    new_user = Users(
        name=data.name,
        email=data.email,
        hashed_password=hash_password(data.password),
        role="manager",
        company_id=data.company_id,
        is_verified=False,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

def revoke_token(db:Session, token: str):
    db_token = db.query(RefreshToken).filter(RefreshToken.token == token).first()
    if not db_token:
        return False
    db_token.revoked = True
    db.commit()
    db.refresh(db_token)
    return True

def delete_user(db:Session, user_id:uuid.UUID):
    db_user = db.get(Users, user_id)
    if not db_user:
        return None
    db.delete(db_user)
    db.commit()
    return True