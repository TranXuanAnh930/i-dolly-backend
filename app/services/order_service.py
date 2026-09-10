import uuid
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload
from app.db.models.cart import Cart
from app.db.models.order import Order, OrderItem
from app.db.models.payment import Payment
from app.db.models.products import Product
from app.db.models.shipping import ShippingStatus, ShippingAddress
from app.db.models.user import Users
from app.schema.order import OrderStatus
from app.schema.shipping import ShippingStatus as SchemaShippingStatus
from app.schema.payment import PaymentCreate
from app.services.payment_service import create_payment
from app.exception.checkout import AddressIdError, CartItemError, InsufficientStockError, PaymentAmountMismatch, UnsupportedGatewayError
from app.exception.db_triggers import DuplicateIdempotencyKeyError, ResaleCapExceededError, commit_or_raise, flush_or_raise, FanOnlyPurchaseError
from app.utils.tax import with_tax
from app.utils.resale import RESALE_CAP_QUANTITY

def checkout(db:Session, user_id:uuid.UUID, payment_data:PaymentCreate):
    user = db.get(Users, user_id)
    if not user or user.role != "fan":
        # Primary check for trg_orders_fan_only — see FanOnlyPurchaseError's docstring.
        raise FanOnlyPurchaseError("Only fan accounts can check out")
    address = (db.query(ShippingAddress).filter(payment_data.shipping_address_id==ShippingAddress.id, ShippingAddress.user_id==user_id).first())
    if not address:
        raise AddressIdError("Invalid address id!")

    if db.query(Payment).filter(Payment.idempotency_key == payment_data.idempotency_key).first():
        raise DuplicateIdempotencyKeyError()  
    
    cart_items = db.query(Cart).filter(Cart.user_id==user_id).all()
    if not cart_items:
        raise CartItemError("No item in cart")
    total_amount = sum(with_tax(item.total_price) for item in cart_items)
    if payment_data.amount!=total_amount:
        raise PaymentAmountMismatch("Payment amount does not match cart total!")
        
    product_ids = [cart_item.product_id for cart_item in cart_items]
    capped_products = db.query(Product).filter(Product.id.in_(product_ids), Product.category.has(is_resale_capped=True)).all()
    capped_product_ids = {product.id for product in capped_products}

    if capped_product_ids:
    # one grouped query across every capped item in the cart, not one query per item
        past_qty = dict(
            db.query(OrderItem.product_id, func.sum(OrderItem.quantity))
            .join(Order).filter(Order.user_id == user_id, OrderItem.product_id.in_(capped_product_ids))
            .group_by(OrderItem.product_id).all()
        )
        for item in cart_items:
            if item.product_id in capped_product_ids and past_qty.get(item.product_id, 0) + item.quantity > RESALE_CAP_QUANTITY:
                raise ResaleCapExceededError(f"product_id={item.product_id} would exceed the {RESALE_CAP_QUANTITY}-unit resale cap")

    products = db.query(Product).filter(Product.id.in_(product_ids)).order_by(Product.id).with_for_update().all()
    for product in products:
        item = next((cart_item for cart_item in cart_items if cart_item.product_id == product.id), None)
        if product.quantity < item.quantity:
            raise InsufficientStockError("Insufficient Stock")
        
    order = Order(user_id=user_id, shipping_address_id=payment_data.shipping_address_id, total_price=float(total_amount))
    db.add(order)
    flush_or_raise(db)  # trg_orders_fan_only fires here (fn_enforce_fan_only_purchase)
    
    payment_res = create_payment(db, user_id, order, payment_data)
    if not payment_res:
        raise UnsupportedGatewayError("Unsupported payment gateway!")

    for product in products:
        item = next((cart_item for cart_item in cart_items if cart_item.product_id == product.id), None)
        product.quantity-=item.quantity
    
    for item in cart_items:
        # Same tax-inclusive treatment as total_amount above — otherwise
        # sum(order_item.price * quantity) drifts 10% below order.total_price,
        # and the order-details line items would show pre-tax figures.
        order_item = OrderItem(
            order_id=order.id,
            product_id=item.product_id,
            quantity=item.quantity,
            price=with_tax(item.price)
        )
        db.add(order_item)

    db.query(Cart).filter(Cart.user_id==user_id).delete()
    commit_or_raise(db)  # trg_orders_fan_only / chk_products_capacity backstop
    db.refresh(order)
    return order

def fetch_placed_order(db:Session, user_id:uuid.UUID):
    order = (
        db.query(Order)
        .filter(Order.user_id==user_id)
        .options(selectinload(Order.items), selectinload(Order.items).selectinload(OrderItem.order_product))
        .all()
    )
    return order

def fetch_single_placed_order(db:Session, user_id:uuid.UUID, order_id:uuid.UUID):
    order = (
        db.query(Order)
        .filter(Order.id==order_id, Order.user_id==user_id)
        .options(selectinload(Order.items))
        .first()
    )
    if not order:
        return False
    return order

def cancel_placed_order(db:Session, user_id:uuid.UUID, order_id:uuid.UUID):
    order = fetch_single_placed_order(db, user_id, order_id)
    if not order:
        return None
    if not order.shippingstatus or order.shippingstatus.status not in (SchemaShippingStatus.pending, SchemaShippingStatus.processing):
        return False
    order.status = OrderStatus.cancelled
    order.shippingstatus.status = SchemaShippingStatus.cancelled
    db.commit()
    db.refresh(order)
    return order

def get_user_shipping_status(db:Session, user_id:uuid.UUID, order_id:uuid.UUID):
    ship_status = db.query(Order).filter(Order.user_id==user_id, Order.id==order_id).options(selectinload(Order.shippingstatus)).first()
    if not ship_status:
        return None
    return ship_status.shippingstatus

def update_shipping_status(db:Session, new_status:SchemaShippingStatus, order_id:uuid.UUID):
    order_shippingstatus = db.query(ShippingStatus).filter(ShippingStatus.order_id==order_id).first()
    if not order_shippingstatus or order_shippingstatus.status == SchemaShippingStatus.cancelled:
        return None
    order_shippingstatus.status = new_status
    db.commit()
    db.refresh(order_shippingstatus)
    return order_shippingstatus