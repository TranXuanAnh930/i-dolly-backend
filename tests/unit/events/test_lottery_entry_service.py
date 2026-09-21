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

def make_mock_fan(id=DEFAULT_ID):
    fan = MagicMock()
    fan.id = id
    fan.role = "fan"
    fan.company_id = None
    return fan

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

def make_mock_concert(id=DEFAULT_ID, company_id=DEFAULT_ID):
    concert = MagicMock()
    concert.id = id
    concert.company_id = company_id
    return concert

def make_mock_ticket_type(id=DEFAULT_ID, concert_id=DEFAULT_ID):
    tt = MagicMock()
    tt.id = id
    tt.concert_id = concert_id
    return tt

def make_mock_campaign(id=DEFAULT_ID, ticket_type_id=DEFAULT_ID, max_entries_per_user=1):
    campaign = MagicMock()
    campaign.id = id
    campaign.ticket_type_id = ticket_type_id
    campaign.max_entries_per_user = max_entries_per_user
    return campaign

def model_get_side_effect(mapping: dict):
    def _side_effect(model, ident=None):
        return mapping.get(model)
    return _side_effect

# ───────────────────────────────────────────────────────────────
# apply_to_lottery
# ───────────────────────────────────────────────────────────────

class TestApplyToLottery:

    def test_non_fan_role_forbidden(self):
        from app.schema.events import LotteryEntryApply
        from app.services.events.lottery_entry_service import LotteryEntryService

        db = MagicMock()
        data = LotteryEntryApply(campaign_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            LotteryEntryService.apply_to_lottery(db, data, make_mock_manager())

    def test_campaign_not_found(self):
        from app.db.models.events import LotteryCampaign
        from app.schema.events import LotteryEntryApply
        from app.services.events.lottery_entry_service import LotteryEntryService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({LotteryCampaign: None})
        data = LotteryEntryApply(campaign_id=MISSING_ID)

        with pytest.raises(NotFoundError):
            LotteryEntryService.apply_to_lottery(db, data, make_mock_fan())

    def test_already_holds_a_live_ticket_rejected(self):
        from app.db.models.events import LotteryCampaign, TicketType
        from app.schema.events import LotteryEntryApply
        from app.services.events.lottery_entry_service import LotteryEntryService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({
            LotteryCampaign: make_mock_campaign(),
            TicketType: make_mock_ticket_type(),
        })
        # existing_ticket lookup: db.query(Ticket).join(...).filter(...).first()
        db.query().join().filter().first.return_value = MagicMock()
        data = LotteryEntryApply(campaign_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            LotteryEntryService.apply_to_lottery(db, data, make_mock_fan())

    def test_no_preference_ranked_rejected(self):
        from app.db.models.events import LotteryCampaign, LotteryPreference, TicketType
        from app.schema.events import LotteryEntryApply
        from app.services.events.lottery_entry_service import LotteryEntryService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({
            LotteryCampaign: make_mock_campaign(),
            TicketType: make_mock_ticket_type(),
        })

        def query_side_effect(model, *cols):
            q = MagicMock()
            if model.__name__ == "Ticket":
                q.join.return_value.filter.return_value.first.return_value = None
            elif model is LotteryPreference:
                q.filter.return_value.first.return_value = None
            return q

        db.query.side_effect = query_side_effect
        data = LotteryEntryApply(campaign_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            LotteryEntryService.apply_to_lottery(db, data, make_mock_fan())

    def test_entry_cap_reached_rejected(self):
        from app.db.models.events import LotteryCampaign, LotteryEntry, LotteryPreference, TicketType
        from app.schema.events import LotteryEntryApply
        from app.services.events.lottery_entry_service import LotteryEntryService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({
            LotteryCampaign: make_mock_campaign(max_entries_per_user=1),
            TicketType: make_mock_ticket_type(),
        })

        def query_side_effect(model, *cols):
            q = MagicMock()
            if model.__name__ == "Ticket":
                q.join.return_value.filter.return_value.first.return_value = None
            elif model is LotteryPreference:
                q.filter.return_value.first.return_value = MagicMock()  # has ranked this tier
            elif model is LotteryEntry:
                q.filter.return_value.count.return_value = 1  # already used their one entry
            return q

        db.query.side_effect = query_side_effect
        data = LotteryEntryApply(campaign_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            LotteryEntryService.apply_to_lottery(db, data, make_mock_fan())

    def test_success(self):
        from app.db.models.events import LotteryCampaign, LotteryEntry, LotteryPreference, TicketType
        from app.schema.events import LotteryEntryApply
        from app.services.events.lottery_entry_service import LotteryEntryService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({
            LotteryCampaign: make_mock_campaign(max_entries_per_user=2),
            TicketType: make_mock_ticket_type(),
        })

        def query_side_effect(model, *cols):
            q = MagicMock()
            if model.__name__ == "Ticket":
                q.join.return_value.filter.return_value.first.return_value = None
            elif model is LotteryPreference:
                q.filter.return_value.first.return_value = MagicMock()
            elif model is LotteryEntry:
                q.filter.return_value.count.return_value = 0
            return q

        db.query.side_effect = query_side_effect
        data = LotteryEntryApply(campaign_id=DEFAULT_ID)

        result = LotteryEntryService.apply_to_lottery(db, data, make_mock_fan())

        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

# ───────────────────────────────────────────────────────────────
# get_my_entries / get_entries_for_campaign
# ───────────────────────────────────────────────────────────────

class TestGetEntries:

    def test_get_my_entries_found(self):
        from app.services.events.lottery_entry_service import LotteryEntryService

        db = MagicMock()
        db.query().options().filter().all.return_value = [MagicMock()]

        result = LotteryEntryService.get_my_entries(db, make_mock_fan())
        assert result is not None

    def test_get_my_entries_empty(self):
        from app.services.events.lottery_entry_service import LotteryEntryService

        db = MagicMock()
        db.query().options().filter().all.return_value = []

        result = LotteryEntryService.get_my_entries(db, make_mock_fan())
        assert result == []

    def test_get_entries_for_campaign_not_found(self):
        from app.db.models.events import LotteryCampaign
        from app.services.events.lottery_entry_service import LotteryEntryService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({LotteryCampaign: None})

        with pytest.raises(NotFoundError):
            LotteryEntryService.get_entries_for_campaign(db, MISSING_ID, make_mock_admin())

    def test_get_entries_for_campaign_manager_wrong_company_forbidden(self):
        from app.db.models.events import Concert, LotteryCampaign, TicketType
        from app.services.events.lottery_entry_service import LotteryEntryService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({
            LotteryCampaign: make_mock_campaign(),
            TicketType: make_mock_ticket_type(),
            Concert: make_mock_concert(company_id=OTHER_ID),
        })
        manager = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            LotteryEntryService.get_entries_for_campaign(db, DEFAULT_ID, manager)

    def test_get_entries_for_campaign_success(self):
        from app.db.models.events import Concert, LotteryCampaign, TicketType
        from app.services.events.lottery_entry_service import LotteryEntryService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({
            LotteryCampaign: make_mock_campaign(),
            TicketType: make_mock_ticket_type(),
            Concert: make_mock_concert(),
        })
        db.query().filter().all.return_value = [MagicMock()]

        result = LotteryEntryService.get_entries_for_campaign(db, DEFAULT_ID, make_mock_admin())
        assert result is not None

    def test_get_entries_for_campaign_empty(self):
        from app.db.models.events import Concert, LotteryCampaign, TicketType
        from app.services.events.lottery_entry_service import LotteryEntryService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({
            LotteryCampaign: make_mock_campaign(),
            TicketType: make_mock_ticket_type(),
            Concert: make_mock_concert(),
        })
        db.query().filter().all.return_value = []

        result = LotteryEntryService.get_entries_for_campaign(db, DEFAULT_ID, make_mock_admin())
        assert result == []
