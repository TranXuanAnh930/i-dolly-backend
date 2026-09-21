import uuid
from unittest.mock import MagicMock

import pytest

# ───────────────────────────────────────────────────────────────
# Id sentinels — plain MagicMock-based unit tests (no real DB), so any
# distinct UUIDs work: DEFAULT_ID stands in for "the id under test",
# MISSING_ID for "doesn't exist".
# ───────────────────────────────────────────────────────────────

DEFAULT_ID = uuid.uuid4()
MISSING_ID = uuid.uuid4()

# ───────────────────────────────────────────────────────────────
# Shipping Service Tests
# ───────────────────────────────────────────────────────────────

class TestShippingService:

    def test_create_shipping_address(self):
        from app.schema.marketplace import ShippingBase
        from app.services.marketplace.shipping_service import ShippingService

        db = MagicMock()
        data = ShippingBase(
            address_line1="123 Main St", city="Mumbai",
            postal_code="400001", state="MH", country="India"
        )

        ShippingService.create_shipping_address(db, DEFAULT_ID, data)
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_fetch_address_found(self):
        from app.services.marketplace.shipping_service import ShippingService

        db = MagicMock()
        db.query().filter().all.return_value = [MagicMock()]

        result = ShippingService.fetch_address(db, DEFAULT_ID)
        assert result is not None

    def test_fetch_address_empty(self):
        from app.services.marketplace.shipping_service import ShippingService

        db = MagicMock()
        db.query().filter().all.return_value = []

        result = ShippingService.fetch_address(db, DEFAULT_ID)
        assert result == []

    def test_delete_address_success(self):
        from app.services.marketplace.shipping_service import ShippingService

        db = MagicMock()
        mock_addr = MagicMock()
        db.query().filter().first.return_value = mock_addr

        result = ShippingService.delete_address(db, DEFAULT_ID, DEFAULT_ID)
        assert result is True
        db.delete.assert_called_once()

    def test_delete_address_not_found(self):
        from app.services.marketplace.shipping_service import ShippingService

        db = MagicMock()
        db.query().filter().first.return_value = None

        result = ShippingService.delete_address(db, DEFAULT_ID, MISSING_ID)
        assert result is None

    def test_get_address_by_id_found(self):
        from app.services.marketplace.shipping_service import ShippingService

        db = MagicMock()
        mock_addr = MagicMock()
        db.query().filter().first.return_value = mock_addr

        result = ShippingService.get_address_by_id(db, DEFAULT_ID)
        assert result == mock_addr

    def test_get_address_by_id_not_found(self):
        from app.services.marketplace.shipping_service import ShippingService

        db = MagicMock()
        db.query().filter().first.return_value = None

        result = ShippingService.get_address_by_id(db, MISSING_ID)
        assert result is None

    def test_update_address_success(self):
        from app.schema.marketplace import ShippingBase
        from app.services.marketplace.shipping_service import ShippingService

        db = MagicMock()
        mock_addr = MagicMock()
        db.query().filter().first.return_value = mock_addr
        data = ShippingBase(
            address_line1="456 New St", address_line2="Apt 2", city="Delhi",
            postal_code="110001", state="DL", country="India",
        )

        result = ShippingService.update_address(db, DEFAULT_ID, data, DEFAULT_ID)

        assert result.address_line1 == "456 New St"
        assert result.city == "Delhi"
        db.commit.assert_called_once()

    def test_update_address_not_found(self):
        from app.exception.common import NotFoundError
        from app.schema.marketplace import ShippingBase
        from app.services.marketplace.shipping_service import ShippingService

        db = MagicMock()
        db.query().filter().first.return_value = None
        data = ShippingBase(
            address_line1="456 New St", city="Delhi",
            postal_code="110001", state="DL", country="India",
        )

        with pytest.raises(NotFoundError):
            ShippingService.update_address(db, DEFAULT_ID, data, MISSING_ID)
