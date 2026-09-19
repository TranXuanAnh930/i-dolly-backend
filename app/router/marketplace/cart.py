import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache.rate_limit import rate_limit, user_key
from app.db.models.identity import Users
from app.db.models.marketplace import Cart
from app.deps.auth import get_current_user
from app.deps.db import get_db
from app.exception.db_triggers import TriggerViolationError
from app.schema.common import MessageResponse
from app.schema.marketplace import CartItem
from app.services.marketplace.cart_service import CartService

router = APIRouter(prefix="/cart", tags=["Cart"])

@router.post("/add_cart", response_model=None)
async def add_in_cart(cart_item:CartItem, user:Users=Depends(get_current_user), _: None = Depends(rate_limit(3, 60, user_key)), db:Session=Depends(get_db)) -> Cart:
    try:
        cart = CartService.add_to_cart(db, cart_item, user.id)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    if cart is None:
        raise HTTPException(status_code=404, detail="Insufficient stock or product not found")
    if cart is False:
        raise HTTPException(status_code=404, detail="User not found")
    return cart

@router.get("/see_cart")
async def check_cart(user:Users=Depends(get_current_user), db:Session=Depends(get_db)) -> dict[str, Any]:
    cart = CartService.see_cart(db, user.id)
    if not cart:
        raise HTTPException(status_code=404, detail="Cart is empty")
    return cart

@router.delete("/delete_cart/{cart_id}", response_model=MessageResponse)
async def delete_cart(cart_id:uuid.UUID, user:Users=Depends(get_current_user), db:Session=Depends(get_db)) -> MessageResponse:
    cart = CartService.remove_cart(db, user.id, cart_id)
    if not cart:
        raise HTTPException(status_code=404, detail="Cart item not found")
    return MessageResponse(msg="Cart item deleted successfully")