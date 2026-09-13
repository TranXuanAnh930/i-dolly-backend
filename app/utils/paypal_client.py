"""Thin PayPal REST API wrapper — Orders v2 (create/capture) + webhook
signature verification. Mirrors app/utils/storage.py's shape: a small,
direct client the rest of the app calls into, no gateway abstraction layer
beyond what PaymentGateway already provides (see docs/project_status.md
§7). Synchronous (httpx.Client), matching every other service in this
codebase — nothing here is async.

Deliberately NOT here: retries, circuit breaking, a custom exception
hierarchy. httpx.HTTPStatusError propagates as-is on a non-2xx response;
the caller (order_service/ticket_service's paypal branch) decides how to
turn that into a checkout-facing error, same as it already does for the
mock gateway's own failure cases.
"""
import json
import time

import httpx

from app.config.settings import settings

_BASE_URLS = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "live": "https://api-m.paypal.com",
}


def _base_url() -> str:
    return _BASE_URLS[settings.PAYPAL_MODE or "sandbox"]


# In-process only — not shared across workers/restarts. Re-fetching a token
# occasionally is cheap; a distributed cache for this would be solving a
# problem this project doesn't have at its scale.
_cached_token: dict = {"access_token": None, "expires_at": 0.0}


def get_access_token() -> str:
    """OAuth2 client-credentials grant, cached until shortly before PayPal
    says it expires (60s buffer, not cut exactly at the wire)."""
    if _cached_token["access_token"] and time.monotonic() < _cached_token["expires_at"]:
        return _cached_token["access_token"]

    response = httpx.post(
        f"{_base_url()}/v1/oauth2/token",
        auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials"},
        timeout=10.0,
    )
    response.raise_for_status()
    data = response.json()

    _cached_token["access_token"] = data["access_token"]
    _cached_token["expires_at"] = time.monotonic() + data["expires_in"] - 60
    return _cached_token["access_token"]


def _auth_headers() -> dict:
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type": "application/json",
    }


def create_order(amount: str, currency: str = "USD") -> dict:
    """Creates a PayPal order (state CREATED, not yet approved/captured).
    amount is a string per PayPal's API (e.g. "19.99") — apply tax/rounding
    before calling this, same as with_tax() already does for the mock
    gateway; this function doesn't touch the value at all."""
    response = httpx.post(
        f"{_base_url()}/v2/checkout/orders",
        headers=_auth_headers(),
        json={
            "intent": "CAPTURE",
            "purchase_units": [
                {"amount": {"currency_code": currency, "value": amount}}
            ],
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


def capture_order(paypal_order_id: str) -> dict:
    """Captures funds for an order the buyer has already approved on
    PayPal's side. Raises httpx.HTTPStatusError (e.g. 422 UNPROCESSABLE_
    ENTITY) if the order isn't in an approved state yet."""
    response = httpx.post(
        f"{_base_url()}/v2/checkout/orders/{paypal_order_id}/capture",
        headers=_auth_headers(),
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


def verify_webhook_signature(headers: dict, body: bytes | str | dict) -> bool:
    """Posts the incoming webhook back to PayPal's own verify-webhook-
    signature endpoint rather than recomputing the CRC32/signature check
    locally (docs/project_status.md §7 — avoids reimplementing PayPal's
    cert-chain verification). `headers` is the incoming request's headers
    (matched case-insensitively below, since header casing isn't
    guaranteed); `body` is the raw or already-parsed webhook event payload.

    Returns True only if PayPal reports "SUCCESS" — treat anything else
    (including a malformed/missing header) as an unverified, untrusted
    event and don't act on it.
    """
    webhook_event = body if isinstance(body, dict) else json.loads(body)
    lower_headers = {k.lower(): v for k, v in headers.items()}

    required = ("paypal-transmission-id", "paypal-transmission-time", "paypal-cert-url", "paypal-auth-algo", "paypal-transmission-sig")
    if not all(h in lower_headers for h in required):
        return False

    response = httpx.post(
        f"{_base_url()}/v1/notifications/verify-webhook-signature",
        headers=_auth_headers(),
        json={
            "transmission_id": lower_headers["paypal-transmission-id"],
            "transmission_time": lower_headers["paypal-transmission-time"],
            "cert_url": lower_headers["paypal-cert-url"],
            "auth_algo": lower_headers["paypal-auth-algo"],
            "transmission_sig": lower_headers["paypal-transmission-sig"],
            "webhook_id": settings.PAYPAL_WEBHOOK_ID,
            "webhook_event": webhook_event,
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json().get("verification_status") == "SUCCESS"
