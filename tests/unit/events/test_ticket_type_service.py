import uuid
from unittest.mock import MagicMock

import pytest

from app.exception.common import BadRequestError, ForbiddenError, NotFoundError

# ───────────────────────────────────────────────────────────────
# Id sentinels — plain MagicMock-based unit tests (no real DB), so any
# distinct UUIDs work: DEFAULT_ID stands in for "the id under test",
# OTHER_ID for "a second, different row", MISSING_ID for "doesn't exist".
# ───────────────────────────────────────────────────────────────

DEFAULT_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()
MISSING_ID = uuid.uuid4()

# ───────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────

def make_mock_manager(company_id=DEFAULT_ID):
    manager = MagicMock()
    manager.role = "manager"
    manager.company_id = company_id
    return manager

def make_mock_admin():
    admin = MagicMock()
    admin.role = "admin"
    admin.company_id = None
    return admin

def make_mock_concert(id=DEFAULT_ID, company_id=DEFAULT_ID, status="scheduled"):
    concert = MagicMock()
    concert.id = id
    concert.company_id = company_id
    concert.status = status
    return concert

def make_mock_ticket_type(id=DEFAULT_ID, concert_id=DEFAULT_ID, price=50.0, total_quantity=100, sold_quantity=0):
    tt = MagicMock()
    tt.id = id
    tt.concert_id = concert_id
    tt.price = price
    tt.total_quantity = total_quantity
    tt.sold_quantity = sold_quantity
    return tt

def model_get_side_effect(mapping: dict):
    def _side_effect(model, ident=None):
        return mapping.get(model)
    return _side_effect

# ───────────────────────────────────────────────────────────────
# Ticket Type Service Tests
# ───────────────────────────────────────────────────────────────

class TestTicketTypeService:

    def test_add_ticket_type_success(self):
        from app.db.models.events import Concert
        from app.schema.events import TicketTypeCreate
        from app.services.events.ticket_type_service import TicketTypeService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Concert: make_mock_concert()})
        data = TicketTypeCreate(concert_id=DEFAULT_ID, tier="vip", price=100.0, total_quantity=50, sale_method="direct")
        manager = make_mock_manager(company_id=DEFAULT_ID)

        result = TicketTypeService.add_ticket_type(db, data, manager)

        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_add_ticket_type_concert_not_found(self):
        from app.db.models.events import Concert
        from app.schema.events import TicketTypeCreate
        from app.services.events.ticket_type_service import TicketTypeService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Concert: None})
        data = TicketTypeCreate(concert_id=MISSING_ID, tier="vip", price=100.0, total_quantity=50, sale_method="direct")

        with pytest.raises(NotFoundError):
            TicketTypeService.add_ticket_type(db, data, make_mock_admin())

    def test_add_ticket_type_manager_wrong_company_forbidden(self):
        from app.db.models.events import Concert
        from app.schema.events import TicketTypeCreate
        from app.services.events.ticket_type_service import TicketTypeService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Concert: make_mock_concert(company_id=OTHER_ID)})
        data = TicketTypeCreate(concert_id=DEFAULT_ID, tier="vip", price=100.0, total_quantity=50, sale_method="direct")
        manager = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            TicketTypeService.add_ticket_type(db, data, manager)

    def test_get_ticket_types_found(self):
        from app.services.events.ticket_type_service import TicketTypeService

        db = MagicMock()
        db.query().filter().all.return_value = [make_mock_ticket_type()]

        result = TicketTypeService.get_ticket_types(db, DEFAULT_ID)
        assert result != []
        assert result is not None

    def test_get_ticket_types_empty(self):
        from app.services.events.ticket_type_service import TicketTypeService

        db = MagicMock()
        db.query().filter().all.return_value = []

        result = TicketTypeService.get_ticket_types(db, MISSING_ID)
        assert result is None

    def test_get_ticket_type_found(self):
        from app.services.events.ticket_type_service import TicketTypeService

        db = MagicMock()
        db.get.return_value = make_mock_ticket_type()

        result = TicketTypeService.get_ticket_type(db, DEFAULT_ID)
        assert result is not None

    def test_get_ticket_type_not_found(self):
        from app.services.events.ticket_type_service import TicketTypeService

        db = MagicMock()
        db.get.return_value = None

        result = TicketTypeService.get_ticket_type(db, MISSING_ID)
        assert result is None

    def test_update_ticket_type_not_found(self):
        from app.schema.events import TicketTypeUpdate
        from app.services.events.ticket_type_service import TicketTypeService

        db = MagicMock()
        db.get.return_value = None
        data = TicketTypeUpdate(price=60.0)

        with pytest.raises(NotFoundError):
            TicketTypeService.update_ticket_type(db, MISSING_ID, data, make_mock_admin())

    def test_update_ticket_type_manager_wrong_company_forbidden(self):
        from app.schema.events import TicketTypeUpdate
        from app.services.events.ticket_type_service import TicketTypeService

        tt = make_mock_ticket_type()
        db = MagicMock()
        # update_ticket_type does db.get(TicketType, id) then db.get(Concert, ...) in that order
        db.get.side_effect = [tt, make_mock_concert(company_id=OTHER_ID)]
        data = TicketTypeUpdate(price=tt.price)
        manager = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            TicketTypeService.update_ticket_type(db, DEFAULT_ID, data, manager)

    def test_update_ticket_type_capacity_locked_once_on_sale(self):
        from app.schema.events import TicketTypeUpdate
        from app.services.events.ticket_type_service import TicketTypeService

        tt = make_mock_ticket_type(total_quantity=100, sold_quantity=10)
        concert = make_mock_concert(status="on_sale")
        db = MagicMock()
        db.get.side_effect = [tt, concert]
        data = TicketTypeUpdate(total_quantity=200)
        manager = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            TicketTypeService.update_ticket_type(db, DEFAULT_ID, data, manager)

    def test_update_ticket_type_capacity_below_sold_quantity_rejected(self):
        from app.schema.events import TicketTypeUpdate
        from app.services.events.ticket_type_service import TicketTypeService

        tt = make_mock_ticket_type(total_quantity=100, sold_quantity=50)
        concert = make_mock_concert(status="scheduled")
        db = MagicMock()
        db.get.side_effect = [tt, concert]
        data = TicketTypeUpdate(total_quantity=10)

        with pytest.raises(BadRequestError):
            TicketTypeService.update_ticket_type(db, DEFAULT_ID, data, make_mock_admin())

    def test_update_ticket_type_price_locked_for_manager(self):
        from app.schema.events import TicketTypeUpdate
        from app.services.events.ticket_type_service import TicketTypeService

        tt = make_mock_ticket_type(price=50.0)
        concert = make_mock_concert(status="scheduled")
        db = MagicMock()
        db.get.side_effect = [tt, concert]
        data = TicketTypeUpdate(price=999.0)
        manager = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            TicketTypeService.update_ticket_type(db, DEFAULT_ID, data, manager)

    def test_update_ticket_type_price_editable_by_admin(self):
        from app.schema.events import TicketTypeUpdate
        from app.services.events.ticket_type_service import TicketTypeService

        tt = make_mock_ticket_type(price=50.0)
        concert = make_mock_concert(status="on_sale")
        db = MagicMock()
        db.get.side_effect = [tt, concert]
        data = TicketTypeUpdate(price=75.0)

        result = TicketTypeService.update_ticket_type(db, DEFAULT_ID, data, make_mock_admin())

        assert result.price == 75.0
        db.commit.assert_called_once()

    def test_delete_ticket_type_not_found(self):
        from app.services.events.ticket_type_service import TicketTypeService

        db = MagicMock()
        db.get.return_value = None

        with pytest.raises(NotFoundError):
            TicketTypeService.delete_ticket_type(db, MISSING_ID, make_mock_admin())

    def test_delete_ticket_type_manager_wrong_company_forbidden(self):
        from app.services.events.ticket_type_service import TicketTypeService

        tt = make_mock_ticket_type()
        concert = make_mock_concert(company_id=OTHER_ID)
        db = MagicMock()
        db.get.side_effect = [tt, concert]
        manager = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            TicketTypeService.delete_ticket_type(db, DEFAULT_ID, manager)

    def test_delete_ticket_type_success(self):
        from app.services.events.ticket_type_service import TicketTypeService

        tt = make_mock_ticket_type()
        concert = make_mock_concert()
        db = MagicMock()
        db.get.side_effect = [tt, concert]

        result = TicketTypeService.delete_ticket_type(db, DEFAULT_ID, make_mock_admin())

        assert result == tt
        db.delete.assert_called_once_with(tt)
        db.commit.assert_called_once()
