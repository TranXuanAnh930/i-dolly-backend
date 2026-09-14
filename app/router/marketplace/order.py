import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.cache.rate_limit import rate_limit, user_key
from app.db.models.identity.user import Users
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
from app.exception.db_triggers import TriggerViolationError
from app.schema.marketplace.order import ManagerOrdersPageRead, Order
from app.schema.marketplace.payment import PaymentCreate
from app.schema.marketplace.shipping import ShippingStatus as SchemaShippingStatus
from app.services.marketplace.order_service import (
    cancel_placed_order,
    checkout,
    fetch_placed_order,
    fetch_single_placed_order,
    get_manager_orders_page,
    get_user_shipping_status,
    update_shipping_status,
)

router = APIRouter(prefix="/order", tags=["Order"])

@router.post("/checkout", response_model=Order)
async def checkout_order(data:PaymentCreate, user:Users=Depends(get_current_user), _:None=Depends(rate_limit(3,60,user_key)), db:Session=Depends(get_db)):
    try:
        order = checkout(db, user.id, data)
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
):
    # A manager is always scoped to their own company regardless of any
    # company_id passed — only an admin (no single company of their own)
    # may pick a different one, same trust boundary as every other manager
    # settings page's write endpoints.
    scoped_company_id = current_user.company_id if current_user.role == "manager" else company_id
    return get_manager_orders_page(db, scoped_company_id, page, limit)

@router.get("/fetch_placed_order", response_model=List[Order])
async def fetch_placed_order_for_user(user:Users=Depends(get_current_user), _:None=Depends(rate_limit(5,60,user_key)), db:Session=Depends(get_db)):
    order = fetch_placed_order(db, user.id)
    if not order:
        raise HTTPException(status_code=404, detail="No orders found")
    return order

@router.get("/single_placed_order/{order_id}", response_model=Order)
async def single_placed_order(order_id:uuid.UUID, user:Users=Depends(get_current_user), _:None=Depends(rate_limit(3,60,user_key)), db:Session=Depends(get_db)):
    order = fetch_single_placed_order(db, user.id, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@router.patch("/cancel/{order_id}", response_model=Order)
async def cancel_order(order_id:uuid.UUID, user:Users=Depends(get_current_user), db:Session=Depends(get_db)):
    order = cancel_placed_order(db, user.id, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found!")
    if order is False:
        raise HTTPException(status_code=400, detail="Order is already shipped and cannot be cancelled")
    return order

@router.get("/shipping_status/{order_id}")
async def shipping_status(order_id:uuid.UUID, user:Users=Depends(get_current_user), db:Session=Depends(get_db)):
    shipstat = get_user_shipping_status(db, user.id, order_id)
    if shipstat is None:
        raise HTTPException(status_code=404, detail="Order not found or not authorized")
    return shipstat

@router.patch("/update_shipping_status/{order_id}")
async def update_status(new_status:SchemaShippingStatus, order_id:uuid.UUID, user:Users=Depends(require_admin), db:Session=Depends(get_db)):
    order = update_shipping_status(db, new_status, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found/is cancelled")
    return order