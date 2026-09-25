"""Synchronous PayPal REST client: Orders v2 create/capture and webhook signature verification.

No retries or custom exceptions: non-2xx responses raise httpx.HTTPStatusError to the caller.
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


# Per-process OAuth token cache.
_cached_token: dict = {"access_token": None, "expires_at": 0.0}


def get_access_token() -> str:
    """Client-credentials OAuth token, cached until 60s before it expires."""
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
    """Create a PayPal order (not yet approved or captured).

    `amount` is a string such as "1100", already tax-inclusive."""
    response = httpx.post(
        f"{_base_url()}/v2/checkout/orders",
        headers=_auth_headers(),
        json={
            "intent": "CAPTURE",
            "purchase_units": [
                {"amount": {"currency_code": currency, "value": amount}}
            ],
            # return/cancel URLs point at the frontend, which calls
            # POST /payment/paypal/capture/{pg_order_id} after the buyer approves.
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "return_url": f"{settings.FRONTEND_BASE_URL}/payment/paypal/return",
                        "cancel_url": f"{settings.FRONTEND_BASE_URL}/payment/paypal/cancel",
                        "user_action": "PAY_NOW",
                    }
                }
            },
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


def extract_approval_url(order_response: dict) -> str | None:
    """Return the buyer approval link ("payer-action", or legacy "approve"), or None."""
    for link in order_response.get("links", []):
        if link.get("rel") in ("payer-action", "approve"):
            return link.get("href")
    return None


def capture_order(paypal_order_id: str) -> dict:
    """Capture an approved order. Raises httpx.HTTPStatusError (e.g. 422) if not approved yet."""
    response = httpx.post(
        f"{_base_url()}/v2/checkout/orders/{paypal_order_id}/capture",
        headers=_auth_headers(),
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


def verify_webhook_signature(headers: dict, body: bytes | str | dict) -> bool:
    """Ask PayPal's verify-webhook-signature endpoint whether this webhook is genuine.

    Headers are matched case-insensitively; `body` may be raw or already parsed. Returns True only
    for a "SUCCESS" verification; missing headers or an unparseable body return False.
    """
    lower_headers = {k.lower(): v for k, v in headers.items()}

    required = ("paypal-transmission-id", "paypal-transmission-time", "paypal-cert-url", "paypal-auth-algo", "paypal-transmission-sig")
    if not all(h in lower_headers for h in required):
        return False

    # Parse the body only after the headers look like a PayPal webhook; a bad body returns False
    # instead of a 500, since anyone can call this endpoint.
    try:
        webhook_event = body if isinstance(body, dict) else json.loads(body)
    except (json.JSONDecodeError, TypeError):
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
