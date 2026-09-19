import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.models.identity import Users
from app.db.models.shared import Notification
from app.db.session import session as db_session
from app.utils.hashing import hash_password
from app.utils.jwt_manager import create_access_token
from main import app

client = TestClient(app)

# ───────────────────────────────────────────────────────────────
# Fixtures — reset_rate_limits is shared, autouse, in
# tests/integration/conftest.py; every test module under this directory
# gets it automatically, no per-file import needed.
# ───────────────────────────────────────────────────────────────

# Notifications are self-scoped per user, so each test mints its own fresh
# fan (rather than sharing the module-wide "demo" account other files use)
# to guarantee no leftover notification from an earlier test bleeds into a
# count/list assertion. type="password_reset" is the one notification type
# with no order/ticket/lottery_entry/concert FK required (Notification
# model's own comment — exactly one of those four is expected to be set,
# depending on type), so it's the cheapest real row to seed directly.
@pytest.fixture
def fan_with_notification():
    db = db_session()
    fan = Users(
        name="Fan", email=f"notif-{uuid.uuid4()}@example.com",
        hashed_password=hash_password("pass123"), role="fan", is_verified=True,
    )
    db.add(fan)
    db.commit()
    db.refresh(fan)
    notification = Notification(user_id=fan.id, type="password_reset")
    db.add(notification)
    db.commit()
    db.refresh(notification)

    token = create_access_token({"sub": str(fan.id)})
    yield {"Authorization": f"Bearer {token}"}, notification.id

    db.delete(notification)
    db.delete(fan)
    db.commit()
    db.close()

@pytest.fixture
def fan_headers_no_notifications():
    db = db_session()
    fan = Users(
        name="Fan", email=f"notif-empty-{uuid.uuid4()}@example.com",
        hashed_password=hash_password("pass123"), role="fan", is_verified=True,
    )
    db.add(fan)
    db.commit()
    db.refresh(fan)
    token = create_access_token({"sub": str(fan.id)})
    yield {"Authorization": f"Bearer {token}"}
    db.delete(fan)
    db.commit()
    db.close()

# ───────────────────────────────────────────────────────────────
# GET /notifications/unread-count
# ───────────────────────────────────────────────────────────────

def test_unread_count_unauthenticated():
    response = client.get("/notifications/unread-count")
    assert response.status_code == 401

def test_unread_count_zero(fan_headers_no_notifications):
    response = client.get("/notifications/unread-count", headers=fan_headers_no_notifications)
    assert response.status_code == 200
    assert response.json()["count"] == 0

def test_unread_count_one(fan_with_notification):
    headers, _ = fan_with_notification
    response = client.get("/notifications/unread-count", headers=headers)
    assert response.status_code == 200
    assert response.json()["count"] == 1

# ───────────────────────────────────────────────────────────────
# GET /notifications/mine
# ───────────────────────────────────────────────────────────────

def test_list_mine_unauthenticated():
    response = client.get("/notifications/mine")
    assert response.status_code == 401

def test_list_mine_empty(fan_headers_no_notifications):
    response = client.get("/notifications/mine", headers=fan_headers_no_notifications)
    assert response.status_code == 404

def test_list_mine_found(fan_with_notification):
    headers, notification_id = fan_with_notification
    response = client.get("/notifications/mine", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == str(notification_id)
    assert data[0]["type"] == "password_reset"
    assert data[0]["is_read"] is False

def test_list_mine_unread_only(fan_with_notification):
    headers, notification_id = fan_with_notification
    # Mark it read, then unread_only=True should no longer return it.
    mark_response = client.post(f"/notifications/{notification_id}/read", headers=headers)
    assert mark_response.status_code == 200

    response = client.get("/notifications/mine", params={"unread_only": True}, headers=headers)
    assert response.status_code == 404

# ───────────────────────────────────────────────────────────────
# POST /notifications/{id}/read
# ───────────────────────────────────────────────────────────────

def test_mark_read_unauthenticated():
    response = client.post(f"/notifications/{uuid.uuid4()}/read")
    assert response.status_code == 401

def test_mark_read_not_found(fan_headers_no_notifications):
    response = client.post(f"/notifications/{uuid.uuid4()}/read", headers=fan_headers_no_notifications)
    assert response.status_code == 404

def test_mark_read_not_owner_forbidden(fan_with_notification, fan_headers_no_notifications):
    _, notification_id = fan_with_notification
    response = client.post(f"/notifications/{notification_id}/read", headers=fan_headers_no_notifications)
    assert response.status_code == 403

def test_mark_read_success_then_drops_out_of_unread_count(fan_with_notification):
    headers, notification_id = fan_with_notification
    response = client.post(f"/notifications/{notification_id}/read", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_read"] is True

    assert client.get("/notifications/unread-count", headers=headers).json()["count"] == 0

# ───────────────────────────────────────────────────────────────
# POST /notifications/read-all
# ───────────────────────────────────────────────────────────────

def test_mark_all_read_unauthenticated():
    response = client.post("/notifications/read-all")
    assert response.status_code == 401

def test_mark_all_read_success(fan_with_notification):
    headers, _ = fan_with_notification
    response = client.post("/notifications/read-all", headers=headers)
    assert response.status_code == 200
    assert "1" in response.json()["msg"]

    assert client.get("/notifications/unread-count", headers=headers).json()["count"] == 0

def test_mark_all_read_nothing_to_mark(fan_headers_no_notifications):
    response = client.post("/notifications/read-all", headers=fan_headers_no_notifications)
    assert response.status_code == 200
    assert "0" in response.json()["msg"]
