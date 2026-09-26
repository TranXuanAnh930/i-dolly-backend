import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.cache.invalidation import CacheInvalidation
from app.db.models.identity import Users
from app.db.models.marketplace import Cart, Order, OrderItem, Payment, Product, ShippingAddress, ShippingStatus
from app.exception.checkout import (
    AddressIdError,
    CartItemError,
    InsufficientStockError,
    PaymentAmountMismatch,
    UnsupportedGatewayError,
)
from app.exception.common import BadRequestError, ForbiddenError, NotFoundError
from app.exception.db_triggers import (
    DuplicateIdempotencyKeyError,
    FanOnlyPurchaseError,
    ResaleCapExceededError,
    commit_or_raise,
    flush_or_raise,
)
from app.schema.identity import UserRole
from app.schema.marketplace import (
    ManagerOrderItemRead,
    ManagerOrderRead,
    ManagerOrdersPageRead,
    OrderStatus,
    PaymentCreate,
    PaymentStatus,
)
from app.schema.marketplace import ShippingStatus as SchemaShippingStatus
from app.schema.shared import NotificationType
from app.services.marketplace.payment_service import PaymentService
from app.services.marketplace.product_service import ProductService
from app.services.shared.notification_service import NotificationService
from app.utils.resale import RESALE_CAP_QUANTITY
from app.utils.tax import with_tax


class OrderService:

    @staticmethod
    def checkout(db:Session, user_id:uuid.UUID, payment_data:PaymentCreate) -> Order:
        user = db.get(Users, user_id)
        if not user or user.role != UserRole.fan:
            # Primary check; trg_orders_fan_only is the backstop.
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
        # One grouped query for every resale-capped item in the cart.
            past_qty = dict(
                db.query(OrderItem.product_id, func.sum(OrderItem.quantity))
                .join(Order).filter(Order.user_id == user_id, OrderItem.product_id.in_(capped_product_ids))
                .group_by(OrderItem.product_id).all()
            )
            for item in cart_items:
                if item.product_id in capped_product_ids and past_qty.get(item.product_id, 0) + item.quantity > RESALE_CAP_QUANTITY:
                    raise ResaleCapExceededError(f"product_id={item.product_id} would exceed the {RESALE_CAP_QUANTITY}-unit resale cap")

        # populate_existing() is required: the resale-cap query already loaded these rows unlocked,
        # and without it the stock check would read those stale copies instead of the locked rows.
        products = db.query(Product).filter(Product.id.in_(product_ids)).order_by(Product.id).with_for_update().populate_existing().all()
        for product in products:
            item = next((cart_item for cart_item in cart_items if cart_item.product_id == product.id), None)
            if product.quantity < item.quantity:
                raise InsufficientStockError("Insufficient Stock")

        order = Order(user_id=user_id, shipping_address_id=payment_data.shipping_address_id, total_price=float(total_amount))
        db.add(order)
        flush_or_raise(db)
        # PaymentService.create_payment creates the ShippingStatus row.

        for item in cart_items:
        # Line-item prices are tax-inclusive, matching total_amount.
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
            NotificationService.create_notification(db, user_id, NotificationType.order_confirmation, order_id=order.id)

        commit_or_raise(db)
        if payment.status == PaymentStatus.success:
            # Stock changed: clear both the list pages and the product detail pages.
            CacheInvalidation.delete_cached_products()
            CacheInvalidation.delete_cached_product_details()
        db.refresh(order)
        return order

    @staticmethod
    def fetch_placed_order(db:Session, user_id:uuid.UUID) -> list[Order]:
        order = (
            db.query(Order)
            .filter(Order.user_id==user_id)
            .options(selectinload(Order.items), selectinload(Order.items).selectinload(OrderItem.order_product))
            .all()
        )
        return order

    @staticmethod
    def fetch_single_placed_order(db:Session, user_id:uuid.UUID, order_id:uuid.UUID) -> Order | None:
        return (
            db.query(Order)
            .filter(Order.id==order_id, Order.user_id==user_id)
            .options(selectinload(Order.items))
            .first()
        )

    # Out of scope: not used by the frontend. Doesn't restock, refund, or bust the product cache.
    @staticmethod
    def cancel_placed_order(db:Session, user_id:uuid.UUID, order_id:uuid.UUID) -> Order:
        order = OrderService.fetch_single_placed_order(db, user_id, order_id)
        if not order:
            raise NotFoundError("Order not found")
        if not order.shippingstatus or order.shippingstatus.status not in (SchemaShippingStatus.pending, SchemaShippingStatus.processing):
            raise BadRequestError("Order is already shipped and cannot be cancelled")
        order.status = OrderStatus.cancelled
        order.shippingstatus.status = SchemaShippingStatus.cancelled
        db.commit()
        db.refresh(order)
        return order

    @staticmethod
    def get_user_shipping_status(db:Session, user_id:uuid.UUID, order_id:uuid.UUID) -> ShippingStatus | None:
        order = db.query(Order).filter(Order.user_id==user_id, Order.id==order_id).options(selectinload(Order.shippingstatus)).first()
        return order.shippingstatus if order else None

    @staticmethod
    def update_shipping_status(db:Session, new_status:SchemaShippingStatus, order_id:uuid.UUID) -> ShippingStatus:
        order_shippingstatus = db.query(ShippingStatus).filter(ShippingStatus.order_id==order_id).first()
        if not order_shippingstatus:
            raise NotFoundError("Order not found")
        if order_shippingstatus.status == SchemaShippingStatus.cancelled:
            raise BadRequestError("Order is cancelled and its shipping status can no longer be updated")
        order_shippingstatus.status = new_status
        # Set explicitly; server_onupdate isn't backed by a DB trigger.
        order_shippingstatus.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(order_shippingstatus)
        return order_shippingstatus

    # --- manager "Ship" button: moves pending/processing -> shipped, only for orders containing one
    # of the manager's company's products (ownerless products count for every company). Admins
    # are unrestricted.

    @staticmethod
    def _manager_order_scope_violation(db: Session, order: Order, current_user: Users) -> bool:
        if current_user.role != UserRole.manager:
            return False
        product_ids = {item.product_id for item in order.items}
        products = db.query(Product).filter(Product.id.in_(product_ids)).all()
        company_by_product = ProductService.resolve_product_company_ids(db, products)
        return not any(company_id in (None, current_user.company_id) for company_id in company_by_product.values())

    @staticmethod
    def ship_order(db: Session, order_id: uuid.UUID, current_user: Users) -> Order:
        order = (
            db.query(Order)
            .filter(Order.id == order_id)
            .options(selectinload(Order.items), selectinload(Order.shippingstatus))
            .first()
        )
        if not order:
            raise NotFoundError("Order not found")
        if OrderService._manager_order_scope_violation(db, order, current_user):
            raise ForbiddenError("Managers can only ship orders containing their own company's products")
        if not order.shippingstatus or order.shippingstatus.status not in (SchemaShippingStatus.pending, SchemaShippingStatus.processing):
            current = order.shippingstatus.status.value if order.shippingstatus else "unknown"
            raise BadRequestError(f"Order cannot be marked shipped from its current status ({current})")
        order.shippingstatus.status = SchemaShippingStatus.shipped
        order.shippingstatus.updated_at = datetime.now(timezone.utc)
        NotificationService.create_notification(db, order.user_id, NotificationType.order_shipped, order_id=order.id)
        db.commit()
        db.refresh(order)
        return order

    # --- manager/admin orders page. An order belongs to a company if it contains one of that
    # company's products (resolved via album_details/merch_details; ownerless products count for
    # every company).

    @staticmethod
    def get_manager_orders_page(db: Session, company_id: uuid.UUID | None, page: int = 1, limit: int = 10) -> ManagerOrdersPageRead:
        products = db.query(Product).all()
        if company_id is None:
            relevant_ids = {p.id for p in products}
        else:
            company_by_product = ProductService.resolve_product_company_ids(db, products)
            relevant_ids = {pid for pid, cid in company_by_product.items() if cid in (None, company_id)}

        if not relevant_ids:
            return ManagerOrdersPageRead(page=page, limit=limit, count=0, data=[])

        order_ids = [
            row[0] for row in
            db.query(OrderItem.order_id).filter(OrderItem.product_id.in_(relevant_ids)).distinct().all()
        ]
        offset = (page - 1) * limit
        orders = (
            db.query(Order)
            .filter(Order.id.in_(order_ids))
            .options(selectinload(Order.items), selectinload(Order.user_item), selectinload(Order.shippingstatus))
            .order_by(Order.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        products_by_id = {p.id: p for p in products}
        data = []
        for order in orders:
            # Only this company's line items are shown.
            items = [item for item in order.items if item.product_id in relevant_ids]
            data.append(ManagerOrderRead(
                id=order.id,
                buyer_name=order.user_item.name if order.user_item else "",
                buyer_email=order.user_item.email if order.user_item else "",
                status=order.status,
                created_at=order.created_at,
                items=[
                    ManagerOrderItemRead(
                        product_id=item.product_id,
                        product_name=products_by_id[item.product_id].name if item.product_id in products_by_id else "",
                        quantity=item.quantity,
                        price=item.price,
                    )
                    for item in items
                ],
                company_total=sum(item.price * item.quantity for item in items),
                shippingstatus=order.shippingstatus,
            ))

        return ManagerOrdersPageRead(page=page, limit=limit, count=len(data), data=data)
