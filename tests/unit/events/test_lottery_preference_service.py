import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

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
SERVICE = "app.services.events.lottery_preference_service.LotteryPreferenceService"
TIER_A, TIER_B = uuid.uuid4(), uuid.uuid4()

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

        with patch(f"{SERVICE}._check_ranking_change_allowed"):
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
        assert result == []

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

# ───────────────────────────────────────────────────────────────
# Ranking changes vs. the lottery draw (_check_ranking_change_allowed)
# ───────────────────────────────────────────────────────────────



def make_mock_campaign(tier=None, status="open", opens_in=-timedelta(days=1), closes_in=timedelta(days=1)):
    # Defaults to an open campaign whose entry window contains "now".
    now = datetime.now(timezone.utc)
    campaign = MagicMock()
    campaign.ticket_type_id = tier or TIER_A
    campaign.status = status
    campaign.entry_start_at = now + opens_in
    campaign.entry_end_at = now + closes_in
    return campaign


def open_campaigns(*tiers):
    return [make_mock_campaign(tier=t) for t in tiers]


def ranking_state(current=(), campaigns=(), entered=()):
    """Patch the three query helpers so the rules can be tested without a database."""
    return (
        patch(f"{SERVICE}._current_tier_ids", return_value=set(current)),
        patch(f"{SERVICE}._campaigns_for_tiers", return_value=list(campaigns)),
        patch(f"{SERVICE}._entered_tier_ids", side_effect=lambda db, tiers, user_id: set(entered) & set(tiers)),
    )


class TestRankingChangeAllowed:

    def _check(self, new, **state):
        from app.services.events.lottery_preference_service import LotteryPreferenceService
        p1, p2, p3 = ranking_state(**state)
        with p1, p2 as campaigns_mock, p3:
            LotteryPreferenceService._check_ranking_change_allowed(MagicMock(), DEFAULT_ID, DEFAULT_ID, set(new))
        return campaigns_mock

    def test_reorder_while_entries_open_is_allowed(self):
        self._check([TIER_B, TIER_A], current=[TIER_A, TIER_B], campaigns=open_campaigns(TIER_A, TIER_B), entered=[TIER_A])

    def test_dropping_a_tier_not_applied_to_is_allowed(self):
        self._check([TIER_A], current=[TIER_A, TIER_B], campaigns=open_campaigns(TIER_A, TIER_B), entered=[TIER_A])

    def test_dropping_a_tier_applied_to_is_rejected(self):
        with pytest.raises(BadRequestError, match="already applied"):
            self._check([TIER_B], current=[TIER_A, TIER_B], campaigns=open_campaigns(TIER_A, TIER_B), entered=[TIER_A])

    def test_change_after_entries_closed_is_rejected(self):
        with pytest.raises(BadRequestError, match="have closed"):
            self._check([TIER_A], current=[TIER_A], campaigns=[make_mock_campaign(closes_in=-timedelta(hours=1))])

    @pytest.mark.parametrize("status", ["drawn", "completed"])
    def test_change_after_draw_is_rejected(self, status):
        with pytest.raises(BadRequestError, match="have closed"):
            self._check([TIER_A], current=[TIER_A], campaigns=[make_mock_campaign(status=status)])

    def test_checks_campaigns_of_current_and_new_tiers(self):
        # A closed campaign on a tier being removed must block the change too.
        campaigns_mock = self._check([TIER_B], current=[TIER_A], campaigns=open_campaigns(TIER_A, TIER_B))
        assert campaigns_mock.call_args.args[1] == {TIER_A, TIER_B}

    def test_ranking_a_tier_without_a_campaign_is_rejected(self):
        with pytest.raises(NotFoundError, match="No lottery campaign"):
            self._check([TIER_A, TIER_B], current=[], campaigns=open_campaigns(TIER_A))

    def test_ranking_before_entries_open_is_rejected(self):
        not_yet_open = make_mock_campaign(tier=TIER_A, opens_in=timedelta(hours=1), closes_in=timedelta(days=1))
        with pytest.raises(BadRequestError, match="haven't opened"):
            self._check([TIER_A], current=[], campaigns=[not_yet_open])

    def test_first_ranking_inside_the_window_is_allowed(self):
        self._check([TIER_A, TIER_B], current=[], campaigns=open_campaigns(TIER_A, TIER_B))


class TestClearPreferencesGuard:

    def test_clear_rejected_when_applied_to_a_tier(self):
        from app.services.events.lottery_preference_service import LotteryPreferenceService
        p1, p2, p3 = ranking_state(current=[TIER_A], campaigns=open_campaigns(TIER_A), entered=[TIER_A])
        db = MagicMock()
        with p1, p2, p3, pytest.raises(BadRequestError, match="already applied"):
            LotteryPreferenceService.clear_my_preferences(db, DEFAULT_ID, make_mock_fan())
        db.commit.assert_not_called()

    def test_clear_rejected_after_entries_closed(self):
        from app.services.events.lottery_preference_service import LotteryPreferenceService
        p1, p2, p3 = ranking_state(current=[TIER_A], campaigns=[make_mock_campaign(tier=TIER_A, closes_in=-timedelta(hours=1))])
        db = MagicMock()
        with p1, p2, p3, pytest.raises(BadRequestError, match="have closed"):
            LotteryPreferenceService.clear_my_preferences(db, DEFAULT_ID, make_mock_fan())
        db.commit.assert_not_called()

    def test_set_preferences_runs_the_guard_before_deleting(self):
        from app.db.models.events import Concert, TicketType
        from app.schema.events import LotteryPreferenceSet
        from app.services.events.lottery_preference_service import LotteryPreferenceService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Concert: make_mock_concert(), TicketType: make_mock_ticket_type(TIER_B)})
        p1, p2, p3 = ranking_state(current=[TIER_A], campaigns=open_campaigns(TIER_A, TIER_B), entered=[TIER_A])
        with p1, p2, p3, pytest.raises(BadRequestError):
            LotteryPreferenceService.set_preferences(
                db, LotteryPreferenceSet(concert_id=DEFAULT_ID, ticket_type_ids_in_order=[TIER_B]), make_mock_fan()
            )
        db.query.return_value.filter.return_value.delete.assert_not_called()
        db.commit.assert_not_called()
