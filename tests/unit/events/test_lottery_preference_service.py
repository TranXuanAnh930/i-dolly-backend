import uuid
from unittest.mock import MagicMock

import pytest

from app.exception.common import BadRequestError, NotFoundError

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

def make_mock_fan(id=DEFAULT_ID):
    fan = MagicMock()
    fan.id = id
    fan.role = "fan"
    return fan

def make_mock_concert(id=DEFAULT_ID):
    concert = MagicMock()
    concert.id = id
    return concert

def make_mock_ticket_type(id, concert_id=DEFAULT_ID, sale_method="lottery"):
    tt = MagicMock()
    tt.id = id
    tt.concert_id = concert_id
    tt.sale_method = sale_method
    return tt

def model_get_side_effect(mapping: dict):
    def _side_effect(model, ident=None):
        return mapping.get(model)
    return _side_effect

# ───────────────────────────────────────────────────────────────
# set_preferences
# ───────────────────────────────────────────────────────────────

class TestSetPreferences:

    def test_concert_not_found(self):
        from app.db.models.events import Concert
        from app.schema.events import LotteryPreferenceSet
        from app.services.events.lottery_preference_service import LotteryPreferenceService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Concert: None})
        data = LotteryPreferenceSet(concert_id=MISSING_ID, ticket_type_ids_in_order=[DEFAULT_ID])

        with pytest.raises(NotFoundError):
            LotteryPreferenceService.set_preferences(db, data, make_mock_fan())

    def test_duplicate_ticket_type_id_rejected(self):
        from app.db.models.events import Concert, TicketType
        from app.schema.events import LotteryPreferenceSet
        from app.services.events.lottery_preference_service import LotteryPreferenceService

        tt_id = uuid.uuid4()
        db = MagicMock()
        db.get.side_effect = model_get_side_effect({
            Concert: make_mock_concert(),
            TicketType: make_mock_ticket_type(tt_id),
        })
        data = LotteryPreferenceSet(concert_id=DEFAULT_ID, ticket_type_ids_in_order=[tt_id, tt_id])

        with pytest.raises(BadRequestError):
            LotteryPreferenceService.set_preferences(db, data, make_mock_fan())

    def test_ticket_type_not_belonging_to_concert_not_found(self):
        from app.db.models.events import Concert, TicketType
        from app.schema.events import LotteryPreferenceSet
        from app.services.events.lottery_preference_service import LotteryPreferenceService

        tt_id = uuid.uuid4()
        db = MagicMock()
        db.get.side_effect = model_get_side_effect({
            Concert: make_mock_concert(id=DEFAULT_ID),
            TicketType: make_mock_ticket_type(tt_id, concert_id=OTHER_ID),
        })
        data = LotteryPreferenceSet(concert_id=DEFAULT_ID, ticket_type_ids_in_order=[tt_id])

        with pytest.raises(NotFoundError):
            LotteryPreferenceService.set_preferences(db, data, make_mock_fan())

    def test_direct_sale_ticket_type_rejected(self):
        from app.db.models.events import Concert, TicketType
        from app.schema.events import LotteryPreferenceSet
        from app.services.events.lottery_preference_service import LotteryPreferenceService

        tt_id = uuid.uuid4()
        db = MagicMock()
        db.get.side_effect = model_get_side_effect({
            Concert: make_mock_concert(id=DEFAULT_ID),
            TicketType: make_mock_ticket_type(tt_id, concert_id=DEFAULT_ID, sale_method="direct"),
        })
        data = LotteryPreferenceSet(concert_id=DEFAULT_ID, ticket_type_ids_in_order=[tt_id])

        with pytest.raises(BadRequestError):
            LotteryPreferenceService.set_preferences(db, data, make_mock_fan())

    def test_success_replaces_existing_and_ranks_in_order(self):
        from app.db.models.events import Concert, TicketType
        from app.schema.events import LotteryPreferenceSet
        from app.services.events.lottery_preference_service import LotteryPreferenceService

        vip_id, premium_id = uuid.uuid4(), uuid.uuid4()
        vip = make_mock_ticket_type(vip_id, concert_id=DEFAULT_ID, sale_method="lottery")
        premium = make_mock_ticket_type(premium_id, concert_id=DEFAULT_ID, sale_method="lottery")

        db = MagicMock()
        concert = make_mock_concert(id=DEFAULT_ID)

        def get_side_effect(model, ident=None):
            if model is Concert:
                return concert
            if model is TicketType:
                return {vip_id: vip, premium_id: premium}.get(ident)
            return None

        db.get.side_effect = get_side_effect
        data = LotteryPreferenceSet(concert_id=DEFAULT_ID, ticket_type_ids_in_order=[vip_id, premium_id])
        fan = make_mock_fan()

        result = LotteryPreferenceService.set_preferences(db, data, fan)

        db.query().filter().delete.assert_called_once()  # old preferences wiped first
        assert db.add.call_count == 2
        db.commit.assert_called_once()
        assert [row.rank for row in result] == [1, 2]
        assert [row.ticket_type_id for row in result] == [vip_id, premium_id]

# ───────────────────────────────────────────────────────────────
# get_my_preferences / clear_my_preferences
# ───────────────────────────────────────────────────────────────

class TestGetAndClearPreferences:

    def test_get_my_preferences_found(self):
        from app.services.events.lottery_preference_service import LotteryPreferenceService

        db = MagicMock()
        db.query().filter().order_by().all.return_value = [MagicMock()]

        result = LotteryPreferenceService.get_my_preferences(db, DEFAULT_ID, make_mock_fan())
        assert result is not None

    def test_get_my_preferences_empty(self):
        from app.services.events.lottery_preference_service import LotteryPreferenceService

        db = MagicMock()
        db.query().filter().order_by().all.return_value = []

        result = LotteryPreferenceService.get_my_preferences(db, DEFAULT_ID, make_mock_fan())
        assert result is None

    def test_clear_my_preferences_deleted_some(self):
        from app.services.events.lottery_preference_service import LotteryPreferenceService

        db = MagicMock()
        db.query().filter().delete.return_value = 2

        result = LotteryPreferenceService.clear_my_preferences(db, DEFAULT_ID, make_mock_fan())
        assert result is True
        db.commit.assert_called_once()

    def test_clear_my_preferences_nothing_to_delete(self):
        from app.services.events.lottery_preference_service import LotteryPreferenceService

        db = MagicMock()
        db.query().filter().delete.return_value = 0

        result = LotteryPreferenceService.clear_my_preferences(db, DEFAULT_ID, make_mock_fan())
        assert result is False
        db.commit.assert_called_once()
