import uuid
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from app.cache.rate_limit import user_key, rate_limit
from app.deps.auth import get_current_user
from app.deps.db import get_db
from app.db.models.user import Users
from app.schema.payment import PaymentResponse
from app.services.payment_service import (
    fetch_all_payments, fetch_payment_status, fetch_ticket_payment_status,
    finalize_paypal_payment,
)
from app.utils.paypal_client import verify_webhook_signature

router = APIRouter(prefix="/payment", tags=["Payment"])

@router.patch("/status/all", response_model=list[PaymentResponse])
async def check_payment_status_all(user:Users=Depends(get_current_user), _:None=Depends(rate_limit(5,60,user_key)), db:Session=Depends(get_db)):
    payment = fetch_all_payments(db, user.id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found!")
    return payment

# Split into /order/{id} and /ticket/{id} (was just /status/{order_id}) —
# a payment for either domain needs its own lookup key now, and FastAPI
# can't tell two identically-shaped {param} routes apart by name alone.
# Nothing else referenced the old path (grepped both repos) so this isn't
# a breaking rename in practice.
@router.patch("/status/order/{order_id}", response_model=PaymentResponse)
async def check_payment_status(order_id:uuid.UUID, user:Users=Depends(get_current_user), _:None=Depends(rate_limit(5,60,user_key)), db:Session=Depends(get_db)):
    payment = fetch_payment_status(db, user.id, order_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found!")
    return payment

@router.patch("/status/ticket/{ticket_id}", response_model=PaymentResponse)
async def check_ticket_payment_status(ticket_id:uuid.UUID, user:Users=Depends(get_current_user), _:None=Depends(rate_limit(5,60,user_key)), db:Session=Depends(get_db)):
    payment = fetch_ticket_payment_status(db, user.id, ticket_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found!")
    return payment

# --- PayPal: two entry points into the same finalize_paypal_payment, since
# either one might be the one that actually resolves a given order first
# (docs/project_status.md §7). ------------------------------------------

# Fast path: the fan's own browser calls this right after approving on
# PayPal's site. Authenticated, so current_user.id can be used as an
# ownership check inside finalize_paypal_payment (does this payment
# actually belong to the caller?) rather than as part of the lookup key —
# the webhook below has no current_user at all and must still work.
@router.post("/paypal/capture/{pg_order_id}", response_model=PaymentResponse)
async def capture_paypal_payment(pg_order_id: str, user: Users = Depends(get_current_user), _: None = Depends(rate_limit(5, 60, user_key)), db: Session = Depends(get_db)):
    # TODO: finalize_paypal_payment should look up Payment by pg_order_id
    # alone (PayPal-side identifiers only), then check payment.user_id ==
    # user.id for ownership — not filter by user_id in the query itself.
    payment = finalize_paypal_payment(db, pg_order_id, user_id=user.id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found, already resolved, or not yours")
    return payment

# Reconciliation path: PayPal calls this on its own schedule, independent
# of any fan's browser — no auth dependency, trust comes entirely from
# verify_webhook_signature below, not from who's logged in (nobody is).
@router.post("/paypal/webhook")
async def paypal_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    if not verify_webhook_signature(request.headers, raw_body):
        # TODO: decide the response here deliberately, not by default —
        # PayPal retries any non-2xx up to 25 times over 3 days. Returning
        # an error stops us from ever trusting an unverifiable event, but
        # also means a transient verification hiccup on a *real* event
        # gets retried rather than silently dropped, which is probably
        # what you want here.
        raise HTTPException(status_code=400, detail="Webhook signature verification failed")

    webhook_event = await request.json()
    # TODO: webhook_event["resource"]["id"] is PayPal's capture id, not the
    # PayPal *order* id finalize_paypal_payment keys on — check
    # webhook_event["resource"]["supplementary_data"]["related_ids"]["order_id"]
    # (or whichever field actually carries it for the event types you
    # subscribed to) before wiring this up for real.
    pg_order_id = webhook_event["resource"]["supplementary_data"]["related_ids"]["order_id"]
    finalize_paypal_payment(db, pg_order_id)

    # Always 200 once the signature is verified, whether or not there was
    # anything left to do (already resolved by the capture endpoint,
    # duplicate delivery, etc.) — a non-2xx here just triggers a retry of
    # an event that was never going to do anything different next time.
    return {"msg": "ok"}
