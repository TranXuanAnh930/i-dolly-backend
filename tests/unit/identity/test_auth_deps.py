import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.deps.auth import get_current_user, get_current_user_optional
from app.utils.jwt_manager import create_access_token


def _request():
    request = MagicMock()
    request.state = MagicMock(spec=[])
    return request


def _db(user=None):
    db = MagicMock()
    db.get.return_value = user
    return db


BAD_TOKENS = {
    "garbage": "not-a-jwt",
    "no_sub": create_access_token({"role": "fan"}),
    "non_uuid_sub": create_access_token({"sub": "not-a-uuid"}),
}


class TestGetCurrentUser:
    @pytest.mark.parametrize("token", BAD_TOKENS.values(), ids=BAD_TOKENS.keys())
    def test_bad_token_is_401(self, token):
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(_request(), token, _db())
        assert exc_info.value.status_code == 401

    def test_unknown_user_is_401(self):
        token = create_access_token({"sub": str(uuid.uuid4())})
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(_request(), token, _db(user=None))
        assert exc_info.value.status_code == 401

    def test_valid_token_returns_user_and_sets_request_state(self):
        user = MagicMock()
        user_id = uuid.uuid4()
        request = _request()
        db = _db(user=user)

        assert get_current_user(request, create_access_token({"sub": str(user_id)}), db) is user
        assert request.state.user is user
        db.get.assert_called_once()
        assert db.get.call_args.args[1] == user_id


class TestGetCurrentUserOptional:
    @pytest.mark.parametrize("token", [None, *BAD_TOKENS.values()])
    def test_missing_or_bad_token_is_none(self, token):
        assert get_current_user_optional(_request(), token, _db()) is None

    def test_unknown_user_is_none(self):
        token = create_access_token({"sub": str(uuid.uuid4())})
        assert get_current_user_optional(_request(), token, _db(user=None)) is None

    def test_valid_token_returns_user(self):
        user = MagicMock()
        token = create_access_token({"sub": str(uuid.uuid4())})
        assert get_current_user_optional(_request(), token, _db(user=user)) is user
