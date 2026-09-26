import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.config.settings import settings
from app.db.models.identity import RefreshToken, Users
from app.exception.common import BadRequestError
from app.schema.identity import UserCreate
from app.utils.email_templates import EmailTemplate
from app.utils.hashing import hash_password, verify_password
from app.utils.jwt_manager import create_access_token, create_email_verification_token, decode_email_token


class AuthService:

    @staticmethod
    def create_user(db:Session, user: UserCreate) -> Users:
        check_existing_user = db.query(Users).filter(Users.email == user.email).first()
        if check_existing_user:
            raise BadRequestError("Email already registered")
        new_user = Users(
            name = user.name,
            email = user.email,
            hashed_password = hash_password(user.password),
            is_verified = False
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return new_user

    @staticmethod
    def authenticate_user(db: Session, email: str, password: str) -> Users | None:
        db_user = db.query(Users).filter(Users.email == email).first()
        if not db_user or not verify_password(password, db_user.hashed_password):
            return None
        return db_user

    @staticmethod
    def create_tokens(db: Session, user: Users) -> dict[str, str]:
        # One active session per user: revoke existing refresh tokens.
        db.query(RefreshToken).filter(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked == False
        ).update({"revoked": True})

        access_token = create_access_token(data={"sub" : str(user.id)})
        refresh_token_str = str(uuid.uuid4())
        expires = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        refresh_token = RefreshToken(
            user_id = user.id,
            token = refresh_token_str,
            expires_at = expires
        )
        db.add(refresh_token)
        db.commit()
        db.refresh(refresh_token)
        return{
            "access_token" : access_token,
            "refresh_token" : refresh_token_str,
            "token" : "bearer"
        }

    @staticmethod
    def verify_refresh_token(db: Session, token: str) -> Users | None:
        db_token = db.query(RefreshToken).filter(RefreshToken.token == token).first()
        if db_token and not db_token.revoked:
            expires = db_token.expires_at
            if expires > datetime.now(timezone.utc):
                db_user = db.query(Users).filter(Users.id == db_token.user_id).first()
                return db_user
        return None

    @staticmethod
    def email_verification_process(user: Users) -> None:
        token = create_email_verification_token(user.id)
        link = f"{settings.BASE_URL}/account/verify?token={token}"
        email_body = EmailTemplate.EMAIL_VERIFICATION.render(email=user.email, link=link)
        celery_app.send_task("app.tasks.email.send_email", args=[user.email, EmailTemplate.EMAIL_VERIFICATION.subject, email_body])

    @staticmethod
    def verify_email_token(db: Session, token: str) -> bool | None:
        user_id = decode_email_token(token, "verify")
        if not user_id:
            return None
        db_user = db.query(Users).filter(Users.id == user_id).first()
        if not db_user or db_user.is_verified:
            return False
        db_user.is_verified = True
        db.commit()
        db.refresh(db_user)
        return True

    @staticmethod
    def cleanup_expired_tokens(db: Session) -> int:
        """Delete expired and revoked refresh tokens from the database."""
        deleted = db.query(RefreshToken).filter(
            (RefreshToken.expires_at < datetime.now(timezone.utc)) | (RefreshToken.revoked == True)
        ).delete(synchronize_session=False)
        db.commit()
        return deleted
