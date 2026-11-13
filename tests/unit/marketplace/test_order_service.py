from unittest.mock import MagicMock

import pytest

from app.exception.common import BadRequestError
from app.schema.identity import UserRole
from app.schema.marketplace import OrderStatus
from app.schema.marketplace import ShippingStatus as SchemaShippingStatus

# ───────────────────────────────────────────────────────────────
# OrderService shipping paths with a MagicMock db: only a paid (confirmed)
# order can move toward delivery (bugs.md #26), and the cancel route stays
# unregistered (bugs.md #14).
# ───────────────────────────────────────────────────────────────


def _order(status, shipping=SchemaShippingStatus.pending):
    order = MagicMock()
    order.status = status
    order.shippingstatus.status = shipping
    return order


def _admin():
    user = MagicMock()
    user.role = UserRole.admin
    return user


def _db_returning(row):
    db = MagicMock()
    db.query.return_value.filter.return_value.options.return_value.first.return_value = row
    db.query.return_value.filter.return_value.first.return_value = row
    return db


class TestShipOrder:

    @pytest.mark.parametrize("status", [OrderStatus.pending, OrderStatus.cancelled])
    def test_unpaid_order_cannot_be_shipped(self, status):
        from app.services.marketplace.order_service import OrderService

        order = _order(status)
        db = _db_returning(order)

        with pytest.raises(BadRequestError) as exc_info:
            OrderService.ship_order(db, order.id, _admin())

        assert exc_info.value.code == "order_not_paid"
        assert order.shippingstatus.status == SchemaShippingStatus.pending
        db.add.assert_not_called()  # no order_shipped notification
        db.commit.assert_not_called()

    @pytest.mark.parametrize("shipping", [SchemaShippingStatus.pending, SchemaShippingStatus.processing])
    def test_paid_order_ships(self, shipping):
        from app.services.marketplace.order_service import OrderService

        order = _order(OrderStatus.confirmed, shipping)
        db = _db_returning(order)

        OrderService.ship_order(db, order.id, _admin())

        assert order.shippingstatus.status == SchemaShippingStatus.shipped
        db.commit.assert_called_once()


class TestUpdateShippingStatus:

    @pytest.mark.parametrize("new_status", [
        SchemaShippingStatus.processing, SchemaShippingStatus.shipped, SchemaShippingStatus.delivered,
    ])
    def test_unpaid_order_cannot_advance(self, new_status):
        from app.services.marketplace.order_service import OrderService

        row = MagicMock()
        row.status = SchemaShippingStatus.pending
        row.orderid.status = OrderStatus.pending
        db = _db_returning(row)

        with pytest.raises(BadRequestError) as exc_info:
            OrderService.update_shipping_status(db, new_status, row.order_id)

        assert exc_info.value.code == "order_not_paid"
        assert row.status == SchemaShippingStatus.pending
        db.commit.assert_not_called()

    def test_unpaid_order_can_be_cancelled(self):
        from app.services.marketplace.order_service import OrderService

        row = MagicMock()
        row.status = SchemaShippingStatus.pending
        row.orderid.status = OrderStatus.pending
        db = _db_returning(row)

        OrderService.update_shipping_status(db, SchemaShippingStatus.cancelled, row.order_id)

        assert row.status == SchemaShippingStatus.cancelled
        db.commit.assert_called_once()

    def test_paid_order_advances(self):
        from app.services.marketplace.order_service import OrderService

        row = MagicMock()
        row.status = SchemaShippingStatus.shipped
        row.orderid.status = OrderStatus.confirmed
        db = _db_returning(row)

        OrderService.update_shipping_status(db, SchemaShippingStatus.delivered, row.order_id)

        assert row.status == SchemaShippingStatus.delivered
        db.commit.assert_called_once()


def test_cancel_route_is_not_registered():
    from app.router.marketplace.order import router

    assert not [route.path for route in router.routes if "cancel" in route.path]
