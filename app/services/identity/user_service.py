import uuid
from typing import Literal

from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.models.identity import RefreshToken, Users
from app.db.models.talent import ManagementCompany
from app.exception.common import BadRequestError, NotFoundError
from app.schema.identity import ManagerCreate, UserRole
from app.schema.shared import NotificationType
from app.services.shared.notification_service import NotificationService
from app.utils.email_templates import EmailTemplate
from app.utils.hashing import hash_password, verify_password
from app.utils.jwt_manager import create_password_reset_token, verify_rtoken_and_get_user_id
from app.celery_app import celery_app

class UserService:

    @staticmethod
    def change_password_process(db: Session, user:Users, old_password: str, new_password: str) -> bool | None:
        password_verification = verify_password(old_password, user.hashed_password)
        if not password_verification:
            return None
        user.hashed_password = hash_password(new_password)
        db.commit()
        db.refresh(user)
        return True

    @staticmethod
    def reset_password_process(db: Session, email: str) -> Literal[True]:
        # Always returns True, whether or not the email is registered — the
        # router gives the same generic response either way, so this endpoint
        # can't be used to enumerate which emails have an account. Only the
        # matched-user branch actually queues anything.
        user = db.query(Users).filter(Users.email == email).first()
        if user:
            token = create_password_reset_token(user.id)
            # Points at the frontend's own /reset-password page (not this API
            # directly, unlike email_verification_process's link) since that
            # page is what actually calls POST /profile/set-password with the
            # token — the fan clicks through, never copy-pastes anything.
            link = f"{settings.FRONTEND_BASE_URL}/reset-password?token={token}"
            email_body = EmailTemplate.RESET_PASSWORD.render(email=user.email, link=link)
            celery_app.send_task("app.tasks.email.send_email", args=[user.email, EmailTemplate.RESET_PASSWORD.subject, email_body])
        return True

    @staticmethod
    def verify_rtoken(db: Session, token: str, new_password: str) -> bool | None:
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
        # A security notice, not the reset-request email above (that one only
        # queues a token, before we know a reset ever actually completes) —
        # carries no order/ticket/lottery_entry/concert FK, just user_id.
        NotificationService.create_notification(db, user.id, NotificationType.password_reset)
        db.commit()
        db.refresh(user)
        return True

    @staticmethod
    def promote_admin(db: Session, user_id: uuid.UUID) -> bool | None:
        user = db.get(Users, user_id)
        if not user:
            return None
        # role is the source of truth for require_admin (architecture.md's own note) — checking/
        # setting only the deprecated is_admin column here left this endpoint unable to actually
        # grant admin access. is_admin is still set alongside role, not removed, since it isn't
        # dropped yet (database-design.md §4's two-step migration plan) and UserOut still reads it.
        if user.role == UserRole.admin:
            return False
        user.role = UserRole.admin
        user.is_admin = True
        db.commit()
        db.refresh(user)
        return True

    @staticmethod
    def create_manager_user(db: Session, data: ManagerCreate) -> Users:
        """Admin-only counterpart to self-register — creates a brand new
        role='manager' account tied to a company in one call, rather than
        promoting an already-registered fan (which /make-admin does for admins,
        but with no company concept). Raises BadRequestError for a taken email,
        NotFoundError for a missing company — see app/exception/common.py."""
        if db.query(Users).filter(Users.email == data.email).first():
            raise BadRequestError("Email already registered")
        if not db.get(ManagementCompany, data.company_id):
            raise NotFoundError("Management company not found")
        new_user = Users(
            name=data.name,
            email=data.email,
            hashed_password=hash_password(data.password),
            role=UserRole.manager,
            company_id=data.company_id,
            is_verified=False,
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return new_user

    @staticmethod
    def revoke_token(db:Session, token: str) -> bool:
        db_token = db.query(RefreshToken).filter(RefreshToken.token == token).first()
        if not db_token:
            return False
        db_token.revoked = True
        db.commit()
        db.refresh(db_token)
        return True

    @staticmethod
    def delete_user(db:Session, user_id:uuid.UUID) -> bool | None:
        db_user = db.get(Users, user_id)
        if not db_user:
            return None
        db.delete(db_user)
        db.commit()
        return True
