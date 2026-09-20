import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.cache.rate_limit import rate_limit, user_key
from app.celery_app import celery_app
from app.db.models.identity import Users
from app.db.models.marketplace import Order as OrderModel
from app.db.models.marketplace import ShippingStatus as ModelShippingStatus
from app.deps.auth import get_current_user, require_admin, require_manager_or_admin
from app.deps.db import get_db
from app.exception.checkout import (
    AddressIdError,
    CartItemError,
    InsufficientStockError,
    PaymentAmountMismatch,
    PaymentFailedError,
    UnsupportedGatewayError,
)
from app.exception.common import ServiceError
from app.exception.db_triggers import TriggerViolationError
from app.schema.identity import UserRole
from app.schema.marketplace.order import ManagerOrdersPageRead, Order, OrderStatus
from app.schema.marketplace.payment import PaymentCreate
from app.schema.marketplace.shipping import ShippingStatus as SchemaShippingStatus
from app.services.marketplace.order_service import OrderService
from app.utils.email_templates import EmailTemplate

router = APIRouter(prefix="/order", tags=["Order"])

@router.post("/checkout", response_model=Order)
async def checkout_order(data:PaymentCreate, user:Users=Depends(get_current_user), _:None=Depends(rate_limit(3,60,user_key)), db:Session=Depends(get_db)) -> OrderModel:
    try:
        order = OrderService.checkout(db, user.id, data)
        if order.status != OrderStatus.cancelled:  # a declined mock payment cancels the order outright — no confirmation email for that
            email_body = EmailTemplate.ORDER_PLACED.render(
                email=user.email, order_id=order.id, total=order.total_price, status=order.status.value
            )
            celery_app.send_task("app.tasks.email.send_email", args=[user.email, EmailTemplate.ORDER_PLACED.subject, email_body])
        return order
    # Order matters here: PaymentFailedError, InsufficientStockError,
    # PaymentAmountMismatch and UnsupportedGatewayError all subclass
    # CartItemError, so the generic (CartItemError, AddressIdError) catch
    # must come last or it swallows every more specific case as a 404.
    except PaymentFailedError as e:
        db.rollback()
        raise HTTPException(status_code=402, detail=str(e)) from e
    except (InsufficientStockError, PaymentAmountMismatch, UnsupportedGatewayError) as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (CartItemError, AddressIdError) as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e
    except TriggerViolationError as e:
        db.rollback()
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    
@router.get("/manager-orders-page", response_model=ManagerOrdersPageRead)
async def get_manager_orders_page_data(
    company_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    current_user: Users = Depends(require_manager_or_admin),
    db: Session = Depends(get_db),
) -> ManagerOrdersPageRead:
    # A manager is always scoped to their own company regardless of any
    # company_id passed — only an admin (no single company of their own)
    # may pick a different one, same trust boundary as every other manager
    # settings page's write endpoints.
    scoped_company_id = current_user.company_id if current_user.role == UserRole.manager else company_id
    return OrderService.get_manager_orders_page(db, scoped_company_id, page, limit)

@router.get("/fetch_placed_order", response_model=List[Order])
async def fetch_placed_order_for_user(user:Users=Depends(get_current_user), _:None=Depends(rate_limit(5,60,user_key)), db:Session=Depends(get_db)) -> list[OrderModel]:
    order = OrderService.fetch_placed_order(db, user.id)
    if not order:
        raise HTTPException(status_code=404, detail="No orders found")
    return order

# FRONTEND: not currently called by i-dolly-frontend. There's no order-
# detail drilldown page — OrderService only calls checkout(), fetchAll()
# (/fetch_placed_order) and getManagerOrdersPage().
@router.get("/single_placed_order/{order_id}", response_model=Order)
async def single_placed_order(order_id:uuid.UUID, user:Users=Depends(get_current_user), _:None=Depends(rate_limit(3,60,user_key)), db:Session=Depends(get_db)) -> OrderModel:
    order = OrderService.fetch_single_placed_order(db, user.id, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

# FRONTEND: not currently called by i-dolly-frontend — no "cancel order" UI
# exists for a fan.
@router.patch("/cancel/{order_id}", response_model=Order)
async def cancel_order(order_id:uuid.UUID, user:Users=Depends(get_current_user), db:Session=Depends(get_db)) -> OrderModel:
    try:
        return OrderService.cancel_placed_order(db, user.id, order_id)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

# FRONTEND: not currently called by i-dolly-frontend — no shipping-status
# view exists for a fan.
@router.get("/shipping_status/{order_id}", response_model=None)
async def shipping_status(order_id:uuid.UUID, user:Users=Depends(get_current_user), db:Session=Depends(get_db)) -> ModelShippingStatus:
    shipstat = OrderService.get_user_shipping_status(db, user.id, order_id)
    if shipstat is None:
        raise HTTPException(status_code=404, detail="Order not found or not authorized")
    return shipstat

# FRONTEND: not currently called by i-dolly-frontend — ManagerOrdersPage
# lists orders but has no control to update a shipping status.
@router.patch("/update_shipping_status/{order_id}", response_model=None)
async def update_status(new_status:SchemaShippingStatus, order_id:uuid.UUID, user:Users=Depends(require_admin), db:Session=Depends(get_db)) -> ModelShippingStatus:
    try:
        return OrderService.update_shipping_status(db, new_status, order_id)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e