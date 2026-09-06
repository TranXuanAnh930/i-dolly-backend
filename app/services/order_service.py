import uuid
from sqlalchemy.orm import Session, selectinload
from app.db.models.cart import Cart
from app.db.models.order import Order, OrderItem
from app.db.models.products import Product
from app.db.models.shipping import ShippingStatus, ShippingAddress
from app.db.models.user import Users
from app.schema.order import OrderStatus
from app.schema.shipping import ShippingStatus as SchemaShippingStatus
from app.schema.payment import PaymentCreate
from app.services.payment_service import create_payment
from app.exception.checkout import AddressIdError, CartItemError, InsufficientStockError, PaymentAmountMismatch, UnsupportedGatewayError
from app.exception.db_triggers import flush_or_raise, FanOnlyPurchaseError
from app.utils.tax import with_tax

def checkout(db:Session, user_id:uuid.UUID, payment_data:PaymentCreate):
    user = db.get(Users, user_id)
    if not user or user.role != "fan":
        # Primary check for trg_orders_fan_only — see FanOnlyPurchaseError's docstring.
        raise FanOnlyPurchaseError("Only fan accounts can check out")
    cart_items = db.query(Cart).filter(Cart.user_id==user_id).options(selectinload(Cart.product)).all()
    if not cart_items:
        raise CartItemError("No item in cart")
    for items in cart_items:
        product = db.query(Product).filter(Product.id==items.product_id).with_for_update().first()
        if product.quantity<items.quantity:
            raise InsufficientStockError("Insufficient Stock") 
    # Cart rows store tax-excluded prices — tax is applied per row here
    # (matching cartStore.subtotal on the frontend) so the amount the
    # client sends and displays throughout checkout is the same
    # tax-included figure this compares against.
    total_amount = sum(with_tax(item.total_price) for item in cart_items)
    
    address =  (db
               .query(ShippingAddress)
               .filter(
                   payment_data.shipping_address_id==ShippingAddress.id, 
                   ShippingAddress.user_id==user_id
                )
               .first()
    )
    if not address:
        raise AddressIdError("Invalid address id!")
    order = Order(user_id=user_id, shipping_address_id=payment_data.shipping_address_id, total_price=float(total_amount))
    db.add(order)
    flush_or_raise(db)  # trg_orders_fan_only fires here (fn_enforce_fan_only_purchase)

    if payment_data.amount!=total_amount:
        raise PaymentAmountMismatch("Payment amount does not match cart total!")
    
    payment_res = create_payment(db, user_id, order, payment_data)
    if not payment_res:
        raise UnsupportedGatewayError("Unsupported payment gateway!")

    for its in cart_items:
        product = db.query(Product).filter(Product.id==its.product_id).with_for_update().first()
        product.quantity-=its.quantity
    
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