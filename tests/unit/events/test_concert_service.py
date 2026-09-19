import uuid
from datetime import datetime, timedelta, timezone
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

NOW = datetime.now(timezone.utc)

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

def make_mock_fan(id=DEFAULT_ID):
    fan = MagicMock()
    fan.id = id
    fan.role = "fan"
    return fan

def make_mock_venue(id=DEFAULT_ID):
    venue = MagicMock()
    venue.id = id
    venue.name = "Arena"
    venue.address = "1 Main St"
    venue.city = "Tokyo"
    venue.country = "Japan"
    venue.total_capacity = 5000
    venue.contact_info = None
    venue.size = "large"
    venue.created_at = NOW
    return venue

def make_mock_concert(id=DEFAULT_ID, company_id=DEFAULT_ID, status="scheduled", venue=None):
    concert = MagicMock()
    concert.id = id
    concert.company_id = company_id
    concert.status = status
    concert.title = "Concert"
    concert.description = None
    concert.event_datetime = NOW + timedelta(days=30)
    concert.doors_open_at = None
    concert.capacity = 500
    concert.created_at = NOW
    concert.updated_at = NOW
    concert.venue = venue or make_mock_venue()
    concert.venue_id = concert.venue.id
    return concert

def make_mock_idol(id=DEFAULT_ID, name="Idol", color=None):
    idol = MagicMock()
    idol.id = id
    idol.name = name
    idol.profile_image_url = None
    idol.color = color
    idol.group_id = None
    return idol

def make_mock_group(id=DEFAULT_ID, name="Group"):
    group = MagicMock()
    group.id = id
    group.name = name
    return group

def make_mock_performer(id=DEFAULT_ID, concert_id=DEFAULT_ID, idol=None, group=None):
    perf = MagicMock()
    perf.id = id
    perf.concert_id = concert_id
    perf.idol_id = idol.id if idol else None
    perf.idol = idol
    perf.group_id = group.id if group else None
    perf.group = group
    return perf

def model_get_side_effect(mapping: dict):
    def _side_effect(model, ident=None):
        return mapping.get(model)
    return _side_effect

# ───────────────────────────────────────────────────────────────
# add_concert / update_concert / delete_concert
# ───────────────────────────────────────────────────────────────

class TestConcertCrud:

    def test_add_concert_success(self):
        from app.db.models.events import Venue
        from app.db.models.talent import ManagementCompany
        from app.schema.events import ConcertCreate
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({ManagementCompany: MagicMock(), Venue: MagicMock()})
        data = ConcertCreate(
            company_id=DEFAULT_ID, venue_id=DEFAULT_ID, title="Concert",
            capacity=500, event_datetime=NOW + timedelta(days=30),
        )

        result = ConcertService.add_concert(db, data, make_mock_admin())

        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_add_concert_manager_wrong_company_forbidden(self):
        from app.schema.events import ConcertCreate
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        data = ConcertCreate(
            company_id=OTHER_ID, venue_id=DEFAULT_ID, title="Concert",
            capacity=500, event_datetime=NOW + timedelta(days=30),
        )
        manager = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            ConcertService.add_concert(db, data, manager)

    def test_add_concert_company_not_found(self):
        from app.db.models.talent import ManagementCompany
        from app.schema.events import ConcertCreate
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({ManagementCompany: None})
        data = ConcertCreate(
            company_id=MISSING_ID, venue_id=DEFAULT_ID, title="Concert",
            capacity=500, event_datetime=NOW + timedelta(days=30),
        )

        with pytest.raises(NotFoundError):
            ConcertService.add_concert(db, data, make_mock_admin())

    def test_add_concert_venue_not_found(self):
        from app.db.models.events import Venue
        from app.db.models.talent import ManagementCompany
        from app.schema.events import ConcertCreate
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({ManagementCompany: MagicMock(), Venue: None})
        data = ConcertCreate(
            company_id=DEFAULT_ID, venue_id=MISSING_ID, title="Concert",
            capacity=500, event_datetime=NOW + timedelta(days=30),
        )

        with pytest.raises(NotFoundError):
            ConcertService.add_concert(db, data, make_mock_admin())

    def test_get_concerts_found(self):
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.query().all.return_value = [make_mock_concert()]

        result = ConcertService.get_concerts(db)
        assert result is not False

    def test_get_concerts_empty(self):
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.query().all.return_value = []

        result = ConcertService.get_concerts(db)
        assert result is False

    def test_update_concert_not_found(self):
        from app.schema.events import ConcertUpdate
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.get.return_value = None
        data = ConcertUpdate(venue_id=DEFAULT_ID, title="Renamed", capacity=500, event_datetime=NOW + timedelta(days=30))

        with pytest.raises(NotFoundError):
            ConcertService.update_concert(db, MISSING_ID, data, make_mock_admin())

    def test_update_concert_manager_wrong_company_forbidden(self):
        from app.schema.events import ConcertUpdate
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.get.return_value = make_mock_concert(company_id=OTHER_ID)
        data = ConcertUpdate(venue_id=DEFAULT_ID, title="Renamed", capacity=500, event_datetime=NOW + timedelta(days=30))
        manager = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            ConcertService.update_concert(db, DEFAULT_ID, data, manager)

    def test_update_concert_date_locked_for_manager_once_on_sale(self):
        from app.schema.events import ConcertUpdate
        from app.services.events.concert_service import ConcertService

        concert = make_mock_concert(status="on_sale")
        db = MagicMock()
        db.get.return_value = concert
        data = ConcertUpdate(
            venue_id=concert.venue_id, title="Renamed", capacity=concert.capacity,
            event_datetime=concert.event_datetime + timedelta(days=1),  # changed
        )
        manager = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            ConcertService.update_concert(db, DEFAULT_ID, data, manager)

    def test_update_concert_non_locked_field_editable_once_on_sale(self):
        from app.db.models.events import Venue
        from app.schema.events import ConcertUpdate
        from app.services.events.concert_service import ConcertService

        concert = make_mock_concert(status="on_sale")
        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Venue: MagicMock()})
        db.get.side_effect = [concert, MagicMock()]  # Concert lookup, then Venue lookup
        data = ConcertUpdate(
            venue_id=concert.venue_id, title="New Title", description="new desc",
            capacity=concert.capacity, event_datetime=concert.event_datetime, doors_open_at=None,
        )
        manager = make_mock_manager(company_id=DEFAULT_ID)

        result = ConcertService.update_concert(db, DEFAULT_ID, data, manager)

        assert result.title == "New Title"
        db.commit.assert_called_once()

    def test_update_concert_venue_not_found(self):
        from app.schema.events import ConcertUpdate
        from app.services.events.concert_service import ConcertService

        concert = make_mock_concert(status="scheduled")
        db = MagicMock()
        db.get.side_effect = [concert, None]  # Concert lookup, then Venue lookup fails
        data = ConcertUpdate(
            venue_id=MISSING_ID, title="Renamed", capacity=concert.capacity,
            event_datetime=concert.event_datetime,
        )

        with pytest.raises(NotFoundError):
            ConcertService.update_concert(db, DEFAULT_ID, data, make_mock_admin())

    def test_delete_concert_not_found(self):
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.get.return_value = None

        with pytest.raises(NotFoundError):
            ConcertService.delete_concert(db, MISSING_ID, make_mock_admin())

    def test_delete_concert_manager_wrong_company_forbidden(self):
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.get.return_value = make_mock_concert(company_id=OTHER_ID)
        manager = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            ConcertService.delete_concert(db, DEFAULT_ID, manager)

    def test_delete_concert_soft_deletes(self):
        from app.services.events.concert_service import ConcertService

        concert = make_mock_concert(status="scheduled")
        db = MagicMock()
        db.get.return_value = concert

        result = ConcertService.delete_concert(db, DEFAULT_ID, make_mock_admin())

        assert result.status == "cancelled"
        db.commit.assert_called_once()

# ───────────────────────────────────────────────────────────────
# concert_performers
# ───────────────────────────────────────────────────────────────

class TestConcertPerformers:

    def test_assign_performer_requires_exactly_one_of_idol_or_group(self):
        from app.schema.events import ConcertPerformerAssign
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        data = ConcertPerformerAssign(concert_id=DEFAULT_ID, idol_id=DEFAULT_ID, group_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            ConcertService.assign_performer(db, data, make_mock_admin())

    def test_assign_performer_concert_not_found(self):
        from app.db.models.events import Concert
        from app.schema.events import ConcertPerformerAssign
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Concert: None})
        data = ConcertPerformerAssign(concert_id=MISSING_ID, idol_id=DEFAULT_ID)

        with pytest.raises(NotFoundError):
            ConcertService.assign_performer(db, data, make_mock_admin())

    def test_assign_performer_manager_wrong_company_forbidden(self):
        from app.db.models.events import Concert
        from app.schema.events import ConcertPerformerAssign
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Concert: make_mock_concert(company_id=OTHER_ID)})
        data = ConcertPerformerAssign(concert_id=DEFAULT_ID, idol_id=DEFAULT_ID)
        manager = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            ConcertService.assign_performer(db, data, manager)

    def test_assign_performer_idol_not_found(self):
        from app.db.models.events import Concert
        from app.db.models.talent import Idol
        from app.schema.events import ConcertPerformerAssign
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Concert: make_mock_concert(), Idol: None})
        data = ConcertPerformerAssign(concert_id=DEFAULT_ID, idol_id=MISSING_ID)

        with pytest.raises(NotFoundError):
            ConcertService.assign_performer(db, data, make_mock_admin())

    def test_assign_performer_success(self):
        from app.db.models.events import Concert
        from app.db.models.talent import Idol
        from app.schema.events import ConcertPerformerAssign
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Concert: make_mock_concert(), Idol: make_mock_idol()})
        data = ConcertPerformerAssign(concert_id=DEFAULT_ID, idol_id=DEFAULT_ID)

        result = ConcertService.assign_performer(db, data, make_mock_admin())

        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_get_performers_found(self):
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.query().filter().all.return_value = [make_mock_performer()]

        result = ConcertService.get_performers(db, DEFAULT_ID)
        assert result is not False

    def test_get_performers_empty(self):
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.query().filter().all.return_value = []

        result = ConcertService.get_performers(db, MISSING_ID)
        assert result is False

    def test_get_all_performers_empty(self):
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.query().all.return_value = []

        result = ConcertService.get_all_performers(db)
        assert result is False

    def test_remove_performer_not_found(self):
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.get.return_value = None

        with pytest.raises(NotFoundError):
            ConcertService.remove_performer(db, MISSING_ID, make_mock_admin())

    def test_remove_performer_manager_wrong_company_forbidden(self):
        from app.services.events.concert_service import ConcertService

        performer = make_mock_performer()
        db = MagicMock()
        db.get.side_effect = [performer, make_mock_concert(company_id=OTHER_ID)]
        manager = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            ConcertService.remove_performer(db, DEFAULT_ID, manager)

    def test_remove_performer_success(self):
        from app.services.events.concert_service import ConcertService

        performer = make_mock_performer()
        db = MagicMock()
        db.get.side_effect = [performer, make_mock_concert()]

        result = ConcertService.remove_performer(db, DEFAULT_ID, make_mock_admin())

        assert result == performer
        db.delete.assert_called_once_with(performer)
        db.commit.assert_called_once()

# ───────────────────────────────────────────────────────────────
# get_events_page / get_manager_events_page
# ───────────────────────────────────────────────────────────────

class TestEventsPages:

    def test_get_events_page_found(self):
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.query().options().all.return_value = [make_mock_concert()]

        result = ConcertService.get_events_page(db)
        assert result is not False

    def test_get_events_page_empty(self):
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.query().options().all.return_value = []

        result = ConcertService.get_events_page(db)
        assert result is False

    def test_get_manager_events_page(self):
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.query().all.return_value = []

        result = ConcertService.get_manager_events_page(db)
        assert result.concerts == []
        assert result.venues == []

# ───────────────────────────────────────────────────────────────
# get_concert_detail_public
# ───────────────────────────────────────────────────────────────

class TestGetConcertDetailPublic:

    def test_not_found(self):
        from app.db.models.events import Concert
        from app.services.events.concert_service import ConcertService

        db = MagicMock()

        def query_side_effect(model, *cols):
            q = MagicMock()
            if model is Concert:
                q.options.return_value.filter.return_value.first.return_value = None
            return q

        db.query.side_effect = query_side_effect

        result = ConcertService.get_concert_detail_public(db, MISSING_ID)
        assert result is False

    def test_lineup_dedups_group_and_solo_credits(self):
        """A group credit expands to its current members, a solo credit is
        just that one idol; the same idol reached via both should appear
        only once in the lineup (concert_service's own dedup rule)."""
        from app.db.models.events import (
            Concert,
            ConcertPerformer,
            DirectSaleCampaign,
            LotteryCampaign,
            LotteryEntry,
            TicketType,
        )
        from app.db.models.talent import Idol
        from app.services.events.concert_service import ConcertService

        concert = make_mock_concert()
        shared_idol = make_mock_idol(id=DEFAULT_ID, name="Shared Idol")
        solo_idol = make_mock_idol(id=OTHER_ID, name="Solo Idol")
        group = make_mock_group()

        group_performer = make_mock_performer(id=uuid.uuid4(), group=group)
        solo_performer = make_mock_performer(id=uuid.uuid4(), idol=solo_idol)
        # Same idol also credited solo (already counted via the group) — must not duplicate.
        duplicate_solo_performer = make_mock_performer(id=uuid.uuid4(), idol=shared_idol)

        db = MagicMock()

        def query_side_effect(model, *cols):
            q = MagicMock()
            if model is Concert:
                q.options.return_value.filter.return_value.first.return_value = concert
            elif model is TicketType:
                q.filter.return_value.all.return_value = []
            elif model is ConcertPerformer:
                q.options.return_value.filter.return_value.all.return_value = [
                    group_performer, solo_performer, duplicate_solo_performer,
                ]
            elif model is Idol:
                # Expands the group credit to its current members — just shared_idol here.
                q.options.return_value.filter.return_value.all.return_value = [shared_idol]
            elif model is LotteryCampaign:
                q.options.return_value.join.return_value.filter.return_value.all.return_value = []
            elif model is DirectSaleCampaign:
                q.join.return_value.filter.return_value.all.return_value = []
            elif model is LotteryEntry:
                q.filter.return_value.group_by.return_value.all.return_value = []
            return q

        db.query.side_effect = query_side_effect

        result = ConcertService.get_concert_detail_public(db, DEFAULT_ID)

        assert len(result.lineup) == 2  # shared_idol once, solo_idol once
        lineup_ids = {i.id for i in result.lineup}
        assert lineup_ids == {DEFAULT_ID, OTHER_ID}
        assert len(result.performing_groups) == 1
        assert result.performing_groups[0].id == group.id
        # Personalized fields stay at their schema defaults — never computed here.
        assert result.has_ticket is False
        assert result.entered_campaign_ids == []

# ───────────────────────────────────────────────────────────────
# get_personalization
# ───────────────────────────────────────────────────────────────

class TestGetPersonalization:

    def test_no_ticket_no_win_no_entries_no_preferences(self):
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.query().join().filter().first.return_value = None
        db.query().join().join().filter().first.return_value = None
        db.query().filter().all.return_value = []
        db.query().filter().order_by().all.return_value = []

        result = ConcertService.get_personalization(db, DEFAULT_ID, make_mock_fan(), campaign_ids=[])

        assert result["has_ticket"] is False
        assert result["has_won_lottery"] is False
        assert result["entered_campaign_ids"] == []
        assert result["my_lottery_preferences"] == []

    def test_has_ticket_and_has_won_lottery(self):
        from app.db.models.events import LotteryEntry, LotteryPreference, Ticket
        from app.services.events.concert_service import ConcertService

        campaign_id = uuid.uuid4()
        db = MagicMock()

        def query_side_effect(model, *cols):
            q = MagicMock()
            if model is Ticket:
                q.join.return_value.filter.return_value.first.return_value = MagicMock()  # has a paid ticket
            elif model is LotteryEntry:
                # db.query(LotteryEntry).join(...).join(...).filter(...).first() — has_won_lottery
                q.join.return_value.join.return_value.filter.return_value.first.return_value = MagicMock()
            elif model is LotteryEntry.campaign_id:
                # db.query(LotteryEntry.campaign_id).filter(...).all() — entered_campaign_ids
                q.filter.return_value.all.return_value = [(campaign_id,)]
            elif model is LotteryPreference:
                q.filter.return_value.order_by.return_value.all.return_value = []
            return q

        db.query.side_effect = query_side_effect

        result = ConcertService.get_personalization(db, DEFAULT_ID, make_mock_fan(), campaign_ids=[campaign_id])

        assert result["has_ticket"] is True
        assert result["has_won_lottery"] is True
        assert result["entered_campaign_ids"] == [campaign_id]

    def test_empty_campaign_ids_skips_entered_campaign_query(self):
        from app.services.events.concert_service import ConcertService

        db = MagicMock()
        db.query().join().filter().first.return_value = None
        db.query().filter().order_by().all.return_value = []

        result = ConcertService.get_personalization(db, DEFAULT_ID, make_mock_fan(), campaign_ids=[])

        assert result["entered_campaign_ids"] == []
