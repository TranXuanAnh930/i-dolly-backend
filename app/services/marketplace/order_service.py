import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.cache.cache_service import delete_cached_products
from app.db.models.identity import Users
from app.db.models.marketplace import Cart, Order, OrderItem, Payment, Product, ShippingAddress, ShippingStatus
from app.exception.checkout import (
    AddressIdError,
    CartItemError,
    InsufficientStockError,
    PaymentAmountMismatch,
    UnsupportedGatewayError,
)
from app.exception.db_triggers import (
    DuplicateIdempotencyKeyError,
    FanOnlyPurchaseError,
    ResaleCapExceededError,
    commit_or_raise,
    flush_or_raise,
)
from app.schema.marketplace import OrderStatus, PaymentCreate, PaymentStatus
from app.schema.marketplace import ShippingStatus as SchemaShippingStatus
from app.services.marketplace.payment_service import PaymentService
from app.services.marketplace.product_service import ProductService
from app.services.shared.notification_service import NotificationService
from app.utils.resale import RESALE_CAP_QUANTITY
from app.utils.tax import with_tax


class OrderService:

    @staticmethod
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
        flush_or_raise(db)

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
        flush_or_raise(db)

        payment = PaymentService.create_payment(db, user_id, order, payment_data)
        if not payment:
            raise UnsupportedGatewayError("Unsupported payment gateway!")

        if payment.status == PaymentStatus.success:
            for product in products:
                item = next((cart_item for cart_item in cart_items if cart_item.product_id == product.id), None)
                product.quantity-=item.quantity
            db.query(Cart).filter(Cart.user_id==payment.user_id, Cart.product_id.in_(product_ids)).delete()
            NotificationService.create_notification(db, user_id, "order_confirmation", order_id=order.id)

        commit_or_raise(db)  # trg_orders_fan_only / chk_products_capacity backstop
        if payment.status == PaymentStatus.success:
            delete_cached_products()
        db.refresh(order)
        return order

    @staticmethod
    def fetch_placed_order(db:Session, user_id:uuid.UUID):
        order = (
            db.query(Order)
            .filter(Order.user_id==user_id)
            .options(selectinload(Order.items), selectinload(Order.items).selectinload(OrderItem.order_product))
            .all()
        )
        return order

    @staticmethod
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

    @staticmethod
    def cancel_placed_order(db:Session, user_id:uuid.UUID, order_id:uuid.UUID):
        order = OrderService.fetch_single_placed_order(db, user_id, order_id)
        if not order:
            return None
        if not order.shippingstatus or order.shippingstatus.status not in (SchemaShippingStatus.pending, SchemaShippingStatus.processing):
            return False
        order.status = OrderStatus.cancelled
        order.shippingstatus.status = SchemaShippingStatus.cancelled
        db.commit()
        db.refresh(order)
        return order

    @staticmethod
    def get_user_shipping_status(db:Session, user_id:uuid.UUID, order_id:uuid.UUID):
        ship_status = db.query(Order).filter(Order.user_id==user_id, Order.id==order_id).options(selectinload(Order.shippingstatus)).first()
        if not ship_status:
            return None
        return ship_status.shippingstatus

    @staticmethod
    def update_shipping_status(db:Session, new_status:SchemaShippingStatus, order_id:uuid.UUID):
        order_shippingstatus = db.query(ShippingStatus).filter(ShippingStatus.order_id==order_id).first()
        if not order_shippingstatus or order_shippingstatus.status == SchemaShippingStatus.cancelled:
            return None
        order_shippingstatus.status = new_status
        db.commit()
        db.refresh(order_shippingstatus)
        return order_shippingstatus

    # --- manager/admin orders page (see product_service.py's manager pages for
    # the same "empty is normal, not a 404" convention). Product has no
    # company_id of its own, so which orders "belong" to a company is resolved
    # the same way ManagerProductsPage already is: via album_details/
    # merch_details -> idol/group -> company_id (resolve_product_company_ids),
    # ownerless products counting as everyone's. Unlike the idols/groups/
    # products/concerts manager-*-page bundles, this one requires real auth
    # (require_manager_or_admin in the router) since orders carry a real
    # customer's purchase history, not public catalog data.

    @staticmethod
    def get_manager_orders_page(db: Session, company_id: uuid.UUID | None, page: int = 1, limit: int = 10):
        products = db.query(Product).all()
        if company_id is None:
            relevant_ids = {p.id for p in products}
        else:
            company_by_product = ProductService.resolve_product_company_ids(db, products)
            relevant_ids = {pid for pid, cid in company_by_product.items() if cid in (None, company_id)}

        if not relevant_ids:
            return {"page": page, "limit": limit, "count": 0, "data": []}

        order_ids = [
            row[0] for row in
            db.query(OrderItem.order_id).filter(OrderItem.product_id.in_(relevant_ids)).distinct().all()
        ]
        offset = (page - 1) * limit
        orders = (
            db.query(Order)
            .filter(Order.id.in_(order_ids))
            .options(selectinload(Order.items), selectinload(Order.user_item))
            .order_by(Order.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        products_by_id = {p.id: p for p in products}
        data = []
        for order in orders:
            # Narrowed to this company's own line items — a manager shouldn't
            # see what else a customer bought from another company in the same
            # checkout, only their own company's part of it.
            items = [item for item in order.items if item.product_id in relevant_ids]
            data.append({
                "id": order.id,
                "buyer_name": order.user_item.name if order.user_item else "",
                "buyer_email": order.user_item.email if order.user_item else "",
                "status": order.status,
                "created_at": order.created_at,
                "items": [
                    {
                        "product_id": item.product_id,
                        "product_name": products_by_id[item.product_id].name if item.product_id in products_by_id else "",
                        "quantity": item.quantity,
                        "price": item.price,
                    }
                    for item in items
                ],
                "company_total": sum(item.price * item.quantity for item in items),
            })

        return {"page": page, "limit": limit, "count": len(data), "data": data}
