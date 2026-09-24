import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# ───────────────────────────────────────────────────────────────
# Id sentinels — plain MagicMock-based unit tests (no real DB), so any
# distinct UUIDs work: DEFAULT_ID stands in for "the id under test",
# OTHER_ID for "a second, different row", MISSING_ID for "doesn't exist".
# ───────────────────────────────────────────────────────────────

DEFAULT_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()
MISSING_ID = uuid.uuid4()

# ───────────────────────────────────────────────────────────────
# Payment Service Tests (mock gateway only — real gateway integration is
# deferred to a later phase)
# ───────────────────────────────────────────────────────────────

class TestPaymentService:

    def test_create_mock_payment_success(self):
        from app.schema.marketplace import PaymentCreate, PaymentGateway
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        def _refresh(obj):
            obj.id = DEFAULT_ID
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)
        db.refresh.side_effect = _refresh
        order = MagicMock()
        order.id = DEFAULT_ID
        order.user_id = DEFAULT_ID
        order.total_price = 1000
        data = PaymentCreate(amount=1000, shipping_address_id=DEFAULT_ID, gateway=PaymentGateway.mock, simulate_succ=True, idempotency_key=uuid.uuid4())

        result = PaymentService.create_payment(db, DEFAULT_ID, order, data)
        assert result is not False
        db.add.assert_called()
        # Deliberately does not commit (payment_service.create_payment's own
        # comment) — the caller commits once, alongside the order/shipment
        # writes it made in the same transaction.
        db.flush.assert_called()

    def test_create_mock_payment_failure(self):
        from app.schema.marketplace import PaymentCreate, PaymentGateway
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        def _refresh(obj):
            obj.id = DEFAULT_ID
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)
        db.refresh.side_effect = _refresh
        order = MagicMock()
        order.id = DEFAULT_ID
        data = PaymentCreate(amount=1000, shipping_address_id=DEFAULT_ID, gateway=PaymentGateway.mock, simulate_succ=False, idempotency_key=uuid.uuid4())

        # simulate_succ=False still returns the (failed-status) Payment row —
        # only an unsupported gateway returns False.
        result = PaymentService.create_payment(db, DEFAULT_ID, order, data)
        assert result is not False

    def test_fetch_payment_status_found(self):
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        mock_payment = MagicMock()
        db.query().filter().first.return_value = mock_payment

        result = PaymentService.fetch_payment_status(db, DEFAULT_ID, DEFAULT_ID)
        assert result == mock_payment

    def test_fetch_payment_status_not_found(self):
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        db.query().filter().first.return_value = None

        result = PaymentService.fetch_payment_status(db, DEFAULT_ID, MISSING_ID)
        assert result is None

    def test_fetch_all_payments(self):
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        db.query().filter().all.return_value = [MagicMock(), MagicMock()]

        result = PaymentService.fetch_all_payments(db, DEFAULT_ID)
        assert len(result) == 2

    def test_fetch_all_payments_empty(self):
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        db.query().filter().all.return_value = []

        result = PaymentService.fetch_all_payments(db, DEFAULT_ID)
        assert result == []

    def test_create_payment_paypal_gateway(self):
        from app.schema.marketplace import PaymentCreate, PaymentGateway
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        order = MagicMock()
        order.id = DEFAULT_ID
        data = PaymentCreate(amount=1000, shipping_address_id=DEFAULT_ID, gateway=PaymentGateway.paypal, idempotency_key=uuid.uuid4())

        with patch(
            "app.services.marketplace.payment_service.create_order",
            return_value={"id": "PAYPAL-ORDER-1"},
        ) as mock_create_order, patch(
            "app.services.marketplace.payment_service.extract_approval_url", return_value="https://paypal.example/approve",
        ):
            result = PaymentService.create_payment(db, DEFAULT_ID, order, data)

        mock_create_order.assert_called_once()
        assert result.pg_order_id == "PAYPAL-ORDER-1"
        assert result.pg_approval_url == "https://paypal.example/approve"
        db.flush.assert_called_once()

    def test_fetch_ticket_payment_status_found(self):
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        mock_payment = MagicMock()
        db.query().filter().first.return_value = mock_payment

        result = PaymentService.fetch_ticket_payment_status(db, DEFAULT_ID, DEFAULT_ID)
        assert result == mock_payment

    def test_fetch_ticket_payment_status_not_found(self):
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        db.query().filter().first.return_value = None

        result = PaymentService.fetch_ticket_payment_status(db, DEFAULT_ID, MISSING_ID)
        assert result is None

    def test_create_ticket_payment_mock_success(self):
        from app.schema.events import TicketCheckoutCreate
        from app.schema.marketplace import PaymentGateway
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        ticket = MagicMock()
        ticket.id = DEFAULT_ID
        ticket.ticket_type.sale_method = "direct"
        data = TicketCheckoutCreate(
            ticket_type_id=DEFAULT_ID, amount=50, gateway=PaymentGateway.mock,
            simulate_succ=True, idempotency_key=uuid.uuid4(),
        )

        result = PaymentService.create_ticket_payment(db, DEFAULT_ID, ticket, data)

        assert ticket.status == "paid"
        db.add.assert_called_once()
        db.flush.assert_called_once()
        assert result.ticket_id == DEFAULT_ID

    def test_create_ticket_payment_mock_declined_direct_cancels_ticket(self):
        from app.schema.events import TicketCheckoutCreate
        from app.schema.marketplace import PaymentGateway
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        ticket = MagicMock()
        ticket.id = DEFAULT_ID
        ticket.ticket_type.sale_method = "direct"
        data = TicketCheckoutCreate(
            ticket_type_id=DEFAULT_ID, amount=50, gateway=PaymentGateway.mock,
            simulate_succ=False, idempotency_key=uuid.uuid4(),
        )

        PaymentService.create_ticket_payment(db, DEFAULT_ID, ticket, data)

        assert ticket.status == "cancelled"

    def test_create_ticket_payment_mock_declined_lottery_leaves_ticket_status(self):
        """A declined payment for a *won* lottery ticket doesn't cancel it —
        the fan can retry paying before their deadline lapses; only a
        direct-sale decline cancels immediately (payment_service.py's own
        branch)."""
        from app.schema.events import WonTicketCheckoutCreate
        from app.schema.marketplace import PaymentGateway
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        ticket = MagicMock()
        ticket.id = DEFAULT_ID
        ticket.status = "pending_payment"
        ticket.ticket_type.sale_method = "lottery"
        data = WonTicketCheckoutCreate(amount=50, gateway=PaymentGateway.mock, simulate_succ=False, idempotency_key=uuid.uuid4())

        PaymentService.create_ticket_payment(db, DEFAULT_ID, ticket, data)

        assert ticket.status == "pending_payment"  # untouched


class TestFinalizePaypalPayment:

    def _mock_ticket_type(self, sale_method="direct", total_quantity=10, sold_quantity=0, concert_id=DEFAULT_ID):
        tt = MagicMock()
        tt.sale_method = sale_method
        tt.total_quantity = total_quantity
        tt.sold_quantity = sold_quantity
        tt.concert_id = concert_id
        return tt

    def _mock_ticket(self, id=DEFAULT_ID, user_id=DEFAULT_ID, status="pending_payment", payment_deadline_at=None):
        ticket = MagicMock()
        ticket.id = id
        ticket.user_id = user_id
        ticket.status = status
        ticket.payment_deadline_at = payment_deadline_at
        return ticket

    def _mock_payment(self, ticket_id=None, order_id=None, user_id=DEFAULT_ID):
        from app.schema.marketplace import PaymentStatus
        payment = MagicMock()
        payment.id = DEFAULT_ID
        payment.ticket_id = ticket_id
        payment.order_id = order_id
        payment.user_id = user_id
        payment.status = PaymentStatus.pending
        return payment

    def test_payment_not_found(self):
        from app.services.marketplace.payment_service import PaymentService

        db = MagicMock()
        db.query().filter().with_for_update().first.return_value = None

        result = PaymentService.finalize_paypal_payment(db, "PAYPAL-ORDER-1")
        assert result is None

    def test_ticket_direct_sale_success_increments_sold_quantity_and_notifies(self):
        from app.db.models.events import Ticket, TicketType
        from app.db.models.marketplace import Payment
        from app.services.marketplace.payment_service import CacheService, PaymentService

        payment = self._mock_payment(ticket_id=DEFAULT_ID)
        ticket = self._mock_ticket()
        ticket_type = self._mock_ticket_type(sale_method="direct", total_quantity=10, sold_quantity=3)

        db = MagicMock()

        def query_side_effect(model):
            q = MagicMock()
            if model is Payment:
                q.filter.return_value.with_for_update.return_value.first.return_value = payment
            elif model is Ticket:
                q.filter.return_value.with_for_update.return_value.first.return_value = ticket
            elif model is TicketType:
                q.filter.return_value.with_for_update.return_value.first.return_value = ticket_type
            return q

        db.query.side_effect = query_side_effect

        with patch(
            "app.services.marketplace.payment_service.capture_order",
            return_value={"status": "COMPLETED"},
        ), patch.object(CacheService, "delete_cached_concert_detail") as mock_invalidate_concert, \
           patch.object(CacheService, "delete_cached_products") as mock_invalidate_products, \
           patch("app.services.marketplace.payment_service.NotificationService.create_notification") as mock_notify:
            result = PaymentService.finalize_paypal_payment(db, "PAYPAL-ORDER-1")

        assert payment.status == "success"
        assert ticket.status == "paid"
        assert ticket_type.sold_quantity == 4
        mock_notify.assert_called_once()
        # A ticket sale moves ticket_types[].sold_quantity, which lives in the
        # cached concert detail — and touches no product stock, so the product
        # caches are deliberately left alone rather than needlessly rebuilt.
        mock_invalidate_concert.assert_called_once_with(ticket_type.concert_id)
        mock_invalidate_products.assert_not_called()
        db.commit.assert_called_once()
        assert result == payment

    def test_ticket_lottery_success_does_not_touch_sold_quantity(self):
        """sold_quantity for a lottery ticket is already incremented at draw
        time (lottery_draw_service) — incrementing it again on payment
        would double-count the seat."""
        from app.db.models.events import Ticket, TicketType
        from app.db.models.marketplace import Payment
        from app.services.marketplace.payment_service import PaymentService

        payment = self._mock_payment(ticket_id=DEFAULT_ID)
        ticket = self._mock_ticket()
        ticket_type = self._mock_ticket_type(sale_method="lottery", total_quantity=10, sold_quantity=5)

        db = MagicMock()

        def query_side_effect(model):
            q = MagicMock()
            if model is Payment:
                q.filter.return_value.with_for_update.return_value.first.return_value = payment
            elif model is Ticket:
                q.filter.return_value.with_for_update.return_value.first.return_value = ticket
            elif model is TicketType:
                q.filter.return_value.with_for_update.return_value.first.return_value = ticket_type
            return q

        db.query.side_effect = query_side_effect

        with patch("app.services.marketplace.payment_service.capture_order", return_value={"status": "COMPLETED"}), \
             patch("app.services.marketplace.payment_service.NotificationService.create_notification"):
            PaymentService.finalize_paypal_payment(db, "PAYPAL-ORDER-1")

        assert ticket_type.sold_quantity == 5  # unchanged

    def test_ticket_declined_direct_cancels(self):
        from app.db.models.events import Ticket, TicketType
        from app.db.models.marketplace import Payment
        from app.services.marketplace.payment_service import PaymentService

        payment = self._mock_payment(ticket_id=DEFAULT_ID)
        ticket = self._mock_ticket()
        ticket_type = self._mock_ticket_type(sale_method="direct")

        db = MagicMock()

        def query_side_effect(model):
            q = MagicMock()
            if model is Payment:
                q.filter.return_value.with_for_update.return_value.first.return_value = payment
            elif model is Ticket:
                q.filter.return_value.with_for_update.return_value.first.return_value = ticket
            elif model is TicketType:
                q.filter.return_value.with_for_update.return_value.first.return_value = ticket_type
            return q

        db.query.side_effect = query_side_effect

        with patch("app.services.marketplace.payment_service.capture_order", return_value={"status": "DECLINED"}):
            PaymentService.finalize_paypal_payment(db, "PAYPAL-ORDER-1")

        assert payment.status == "failed"
        assert ticket.status == "cancelled"

    def test_ticket_not_pending_payment_returns_none(self):
        from app.db.models.events import Ticket
        from app.db.models.marketplace import Payment
        from app.services.marketplace.payment_service import PaymentService

        payment = self._mock_payment(ticket_id=DEFAULT_ID)
        ticket = self._mock_ticket(status="paid")  # already resolved

        db = MagicMock()

        def query_side_effect(model):
            q = MagicMock()
            if model is Payment:
                q.filter.return_value.with_for_update.return_value.first.return_value = payment
            elif model is Ticket:
                q.filter.return_value.with_for_update.return_value.first.return_value = ticket
            return q

        db.query.side_effect = query_side_effect

        result = PaymentService.finalize_paypal_payment(db, "PAYPAL-ORDER-1")
        assert result is None

    def test_order_success_decrements_stock_and_clears_cart(self):
        from app.db.models.events import Ticket
        from app.db.models.marketplace import Cart, Order, OrderItem, Payment, Product
        from app.services.marketplace.payment_service import CacheService, PaymentService

        payment = self._mock_payment(order_id=DEFAULT_ID)
        order = MagicMock()
        order.id = DEFAULT_ID
        order.user_id = DEFAULT_ID
        from app.schema.marketplace import OrderStatus
        order.status = OrderStatus.pending

        order_item = MagicMock()
        order_item.product_id = OTHER_ID
        order_item.quantity = 2

        product = MagicMock()
        product.id = OTHER_ID
        product.quantity = 10

        db = MagicMock()

        def query_side_effect(model):
            q = MagicMock()
            if model is Payment:
                q.filter.return_value.with_for_update.return_value.first.return_value = payment
            elif model is Ticket:
                pass
            elif model is Order:
                q.filter.return_value.with_for_update.return_value.first.return_value = order
            elif model is OrderItem:
                q.filter.return_value.all.return_value = [order_item]
            elif model is Product:
                q.filter.return_value.with_for_update.return_value.all.return_value = [product]
            elif model is Cart:
                q.filter.return_value.delete.return_value = None
            return q

        db.query.side_effect = query_side_effect

        with patch(
            "app.services.marketplace.payment_service.capture_order",
            return_value={"status": "COMPLETED"},
        ), patch.object(CacheService, "delete_cached_products") as mock_invalidate, \
           patch("app.services.marketplace.payment_service.NotificationService.create_notification") as mock_notify:
            result = PaymentService.finalize_paypal_payment(db, "PAYPAL-ORDER-1")

        assert payment.status == "success"
        assert product.quantity == 8  # 10 - 2
        assert order.status == "confirmed"
        mock_notify.assert_called_once()
        mock_invalidate.assert_called_once()
        assert result == payment

    def test_order_insufficient_stock_returns_none(self):
        from app.db.models.events import Ticket
        from app.db.models.marketplace import Order, OrderItem, Payment, Product
        from app.schema.marketplace import OrderStatus
        from app.services.marketplace.payment_service import PaymentService

        payment = self._mock_payment(order_id=DEFAULT_ID)
        order = MagicMock()
        order.id = DEFAULT_ID
        order.user_id = DEFAULT_ID
        order.status = OrderStatus.pending

        order_item = MagicMock()
        order_item.product_id = OTHER_ID
        order_item.quantity = 100  # more than in stock

        product = MagicMock()
        product.id = OTHER_ID
        product.quantity = 1

        db = MagicMock()

        def query_side_effect(model):
            q = MagicMock()
            if model is Payment:
                q.filter.return_value.with_for_update.return_value.first.return_value = payment
            elif model is Ticket:
                pass
            elif model is Order:
                q.filter.return_value.with_for_update.return_value.first.return_value = order
            elif model is OrderItem:
                q.filter.return_value.all.return_value = [order_item]
            elif model is Product:
                q.filter.return_value.with_for_update.return_value.all.return_value = [product]
            return q

        db.query.side_effect = query_side_effect

        result = PaymentService.finalize_paypal_payment(db, "PAYPAL-ORDER-1")
        assert result is None

    def test_order_declined_cancels(self):
        from app.db.models.events import Ticket
        from app.db.models.marketplace import Order, OrderItem, Payment, Product
        from app.schema.marketplace import OrderStatus
        from app.services.marketplace.payment_service import PaymentService

        payment = self._mock_payment(order_id=DEFAULT_ID)
        order = MagicMock()
        order.id = DEFAULT_ID
        order.user_id = DEFAULT_ID
        order.status = OrderStatus.pending

        order_item = MagicMock()
        order_item.product_id = OTHER_ID
        order_item.quantity = 1

        product = MagicMock()
        product.id = OTHER_ID
        product.quantity = 10

        db = MagicMock()

        def query_side_effect(model):
            q = MagicMock()
            if model is Payment:
                q.filter.return_value.with_for_update.return_value.first.return_value = payment
            elif model is Ticket:
                pass
            elif model is Order:
                q.filter.return_value.with_for_update.return_value.first.return_value = order
            elif model is OrderItem:
                q.filter.return_value.all.return_value = [order_item]
            elif model is Product:
                q.filter.return_value.with_for_update.return_value.all.return_value = [product]
            return q

        db.query.side_effect = query_side_effect

        with patch("app.services.marketplace.payment_service.capture_order", return_value={"status": "DECLINED"}):
            PaymentService.finalize_paypal_payment(db, "PAYPAL-ORDER-1")

        assert payment.status == "failed"
        assert order.status == "cancelled"

    def test_order_finalize_updates_existing_shipping_status_not_insert(self):
        # Regression for docs/bugs.md #1: create_payment already made this order's
        # shipping_status row at checkout — finalize must update it, never add a second.
        from app.db.models.events import Ticket
        from app.db.models.marketplace import Order, OrderItem, Payment, Product, ShippingStatus
        from app.schema.marketplace import OrderStatus
        from app.schema.marketplace import ShippingStatus as SchemaShipStatus
        from app.services.marketplace.payment_service import PaymentService

        payment = self._mock_payment(order_id=DEFAULT_ID)
        order = MagicMock()
        order.id = DEFAULT_ID
        order.user_id = DEFAULT_ID
        order.status = OrderStatus.pending

        order_item = MagicMock()
        order_item.product_id = OTHER_ID
        order_item.quantity = 1

        product = MagicMock()
        product.id = OTHER_ID
        product.quantity = 10

        existing_ship_status = MagicMock()
        existing_ship_status.status = SchemaShipStatus.pending

        db = MagicMock()

        def query_side_effect(model):
            q = MagicMock()
            if model is Payment:
                q.filter.return_value.with_for_update.return_value.first.return_value = payment
            elif model is Ticket:
                pass
            elif model is Order:
                q.filter.return_value.with_for_update.return_value.first.return_value = order
            elif model is OrderItem:
                q.filter.return_value.all.return_value = [order_item]
            elif model is Product:
                q.filter.return_value.with_for_update.return_value.all.return_value = [product]
            elif model is ShippingStatus:
                q.filter.return_value.first.return_value = existing_ship_status
            return q

        db.query.side_effect = query_side_effect

        with patch("app.services.marketplace.payment_service.capture_order", return_value={"status": "DECLINED"}):
            PaymentService.finalize_paypal_payment(db, "PAYPAL-ORDER-1")

        assert existing_ship_status.status == SchemaShipStatus.cancelled
        added = [call.args[0] for call in db.add.call_args_list]
        assert not any(isinstance(obj, ShippingStatus) for obj in added)
