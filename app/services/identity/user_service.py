import uuid
from typing import Literal

from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.config.settings import settings
from app.db.models.identity import RefreshToken, Users
from app.db.models.talent import ManagementCompany
from app.exception.common import BadRequestError, NotFoundError
from app.schema.identity import ManagerCreate, UserRole
from app.schema.shared import NotificationType
from app.services.shared.notification_service import NotificationService
from app.utils.email_templates import EmailTemplate
from app.utils.hashing import hash_password, verify_password
from app.utils.jwt_manager import create_password_reset_token, decode_email_token


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
        # Always returns True so the endpoint can't be used to discover registered emails.
        user = db.query(Users).filter(Users.email == email).first()
        if user:
            token = create_password_reset_token(user.id)
            # Links to the frontend's reset page, which submits the token to POST /profile/set-password.
            link = f"{settings.FRONTEND_BASE_URL}/reset-password?token={token}"
            email_body = EmailTemplate.RESET_PASSWORD.render(email=user.email, link=link)
            celery_app.send_task("app.tasks.email.send_email", args=[user.email, EmailTemplate.RESET_PASSWORD.subject, email_body])
        return True

    @staticmethod
    def verify_rtoken(db: Session, token: str, new_password: str) -> bool | None:
        user_id = decode_email_token(token, "reset")
        if not user_id:
            return False
        user = db.query(Users).filter(Users.id == user_id).first()
        if not user:
            return None
        user.hashed_password = hash_password(new_password)
        # Revoke all refresh tokens so existing sessions end with the reset.
        db.query(RefreshToken).filter(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked == False
        ).update({"revoked": True})
        # Security notice that the password was changed.
        NotificationService.create_notification(db, user.id, NotificationType.password_reset)
        db.commit()
        db.refresh(user)
        return True

    @staticmethod
    def promote_admin(db: Session, user_id: uuid.UUID) -> bool | None:
        user = db.get(Users, user_id)
        if not user:
            return None
        # role is what require_admin checks; is_admin is a deprecated column kept in sync until it's
        # dropped.
        if user.role == UserRole.admin:
            return False
        user.role = UserRole.admin
        user.is_admin = True
        db.commit()
        db.refresh(user)
        return True

    @staticmethod
    def create_manager_user(db: Session, data: ManagerCreate) -> Users:
        """Admin-only: create a manager account for a company.

        Raises BadRequestError for a taken email, NotFoundError for a missing company."""
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
