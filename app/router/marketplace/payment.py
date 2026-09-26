import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.cache.rate_limit import rate_limit, user_key
from app.db.models.identity import Users
from app.db.models.marketplace import Payment
from app.deps.auth import get_current_user
from app.deps.db import get_db
from app.schema.common import MessageResponse
from app.schema.marketplace import PaymentResponse
from app.services.marketplace.payment_service import PaymentService
from app.utils.paypal_client import order_id_from_webhook, verify_webhook_signature

router = APIRouter(prefix="/payment", tags=["Payment"])

async def _raw_body(request: Request) -> bytes:
    # Reads the body asynchronously so the webhook handler itself can be a sync `def`.
    return await request.body()

# Not used by the frontend.
@router.patch("/status/all", response_model=list[PaymentResponse])
def check_payment_status_all(user:Users=Depends(get_current_user), _:None=Depends(rate_limit(20,60,user_key)), db:Session=Depends(get_db)) -> list[Payment]:
    return PaymentService.fetch_all_payments(db, user.id)

# Separate lookups for order payments and ticket payments.
@router.patch("/status/order/{order_id}", response_model=PaymentResponse)
def check_payment_status(order_id:uuid.UUID, user:Users=Depends(get_current_user), _:None=Depends(rate_limit(20,60,user_key)), db:Session=Depends(get_db)) -> Payment:
    payment = PaymentService.fetch_payment_status(db, user.id, order_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found!")
    return payment

@router.patch("/status/ticket/{ticket_id}", response_model=PaymentResponse)
def check_ticket_payment_status(ticket_id:uuid.UUID, user:Users=Depends(get_current_user), _:None=Depends(rate_limit(20,60,user_key)), db:Session=Depends(get_db)) -> Payment:
    payment = PaymentService.fetch_ticket_payment_status(db, user.id, ticket_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found!")
    return payment

# --- PayPal: both endpoints below call finalize_paypal_payment; whichever arrives first resolves it.

# Called by the fan's browser after approving on PayPal; verifies the payment belongs to the caller.
@router.post("/paypal/capture/{pg_order_id}", response_model=PaymentResponse)
def capture_paypal_payment(pg_order_id: str, user: Users = Depends(get_current_user), _: None = Depends(rate_limit(5, 60, user_key)), db: Session = Depends(get_db)) -> Payment:
    payment = PaymentService.finalize_paypal_payment(db, pg_order_id, user_id=user.id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found, already resolved, or not yours")
    return payment

# Called by PayPal. No user auth; trust comes from the signature check.
@router.post("/paypal/webhook", response_model=MessageResponse)
def paypal_webhook(request: Request, raw_body: bytes = Depends(_raw_body), db: Session = Depends(get_db)) -> MessageResponse:
    if not verify_webhook_signature(request.headers, raw_body):
        raise HTTPException(status_code=400, detail="Webhook signature verification failed")

    pg_order_id = order_id_from_webhook(json.loads(raw_body))
    # Events that don't refer to an order are acknowledged and ignored.
    if pg_order_id:
        PaymentService.finalize_paypal_payment(db, pg_order_id)

    # Return 200 whenever the signature is valid, even if nothing was left to do; a non-2xx
    # response makes PayPal retry.
    return MessageResponse(msg="ok")