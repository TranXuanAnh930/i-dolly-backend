import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt

from app.config.settings import settings
from app.utils.jwt_manager import (
    create_email_verification_token,
    create_password_reset_token,
    decode_email_token,
    decode_password_reset_token,
    password_fingerprint,
    password_fingerprint_matches,
)

USER_ID = uuid.uuid4()
HASH = "$2b$12$abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUV"


def test_reset_token_round_trips_with_a_fingerprint_of_the_hash():
    token = create_password_reset_token(USER_ID, HASH)

    user_id, fingerprint = decode_password_reset_token(token)

    assert user_id == USER_ID
    assert fingerprint == password_fingerprint(HASH)
    assert password_fingerprint_matches(fingerprint, HASH)
    assert not password_fingerprint_matches(fingerprint, HASH + "x")


def test_the_password_hash_is_not_in_the_token():
    claims = jwt.get_unverified_claims(create_password_reset_token(USER_ID, HASH))
    assert HASH not in str(claims)


def test_a_reset_token_without_a_fingerprint_is_rejected():
    # The shape every reset link had before bugs.md #19.
    old_style = jwt.encode(
        {"sub": str(USER_ID), "type": "reset", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.JWT_EMAIL_SECRET_KEY, algorithm=settings.JWT_ALGORITHM,
    )
    assert decode_password_reset_token(old_style) is None


def test_token_types_are_not_interchangeable():
    assert decode_password_reset_token(create_email_verification_token(USER_ID)) is None
    assert decode_email_token(create_password_reset_token(USER_ID, HASH), "verify") is None
    assert decode_email_token(create_email_verification_token(USER_ID), "verify") == USER_ID


def test_garbage_and_expired_tokens_are_rejected():
    expired = jwt.encode(
        {"sub": str(USER_ID), "type": "reset", "pwd": password_fingerprint(HASH),
         "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        settings.JWT_EMAIL_SECRET_KEY, algorithm=settings.JWT_ALGORITHM,
    )
    assert decode_password_reset_token(expired) is None
    assert decode_password_reset_token("not-a-token") is None
