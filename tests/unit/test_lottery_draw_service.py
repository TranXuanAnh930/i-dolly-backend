import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.db.models.concert import Concert
from app.db.models.ticket_type import TicketType
from app.db.models.lottery_campaign import LotteryCampaign
from app.db.models.lottery_preference import LotteryPreference
from app.db.models.lottery_entry import LotteryEntry

# ─────────────────────────────────────────────────────────────
# Id sentinels — see test_services.py's own note: plain MagicMock-based
# unit tests (no real DB), any distinct UUIDs work.
# ─────────────────────────────────────────────────────────────

CONCERT_ID = uuid.uuid4()
COMPANY_ID = uuid.uuid4()
OTHER_COMPANY_ID = uuid.uuid4()
VIP_TT_ID = uuid.uuid4()
PREMIUM_TT_ID = uuid.uuid4()
VIP_CAMPAIGN_ID = uuid.uuid4()
PREMIUM_CAMPAIGN_ID = uuid.uuid4()

PAST = datetime.now(timezone.utc) - timedelta(hours=1)
FUTURE = datetime.now(timezone.utc) + timedelta(hours=1)

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def make_mock_user(role="fan", company_id=None, id=None):
    user = MagicMock()
    user.id = id or uuid.uuid4()
    user.role = role
    user.company_id = company_id
    return user


def make_mock_concert(id=CONCERT_ID, company_id=COMPANY_ID):
    concert = MagicMock()
    concert.id = id
    concert.company_id = company_id
    return concert


def make_mock_ticket_type(id, concert_id=CONCERT_ID, total_quantity=10, sold_quantity=0):
    tt = MagicMock()
    tt.id = id
    tt.concert_id = concert_id
    tt.total_quantity = total_quantity
    tt.sold_quantity = sold_quantity
    return tt


def make_mock_campaign(id, ticket_type_id, status="open", entry_end_at=PAST, payment_deadline_hours=48):
    campaign = MagicMock()
    campaign.id = id
    campaign.ticket_type_id = ticket_type_id
    campaign.status = status
    campaign.entry_end_at = entry_end_at
    campaign.payment_deadline_hours = payment_deadline_hours
    return campaign


def make_mock_preference(user_id, ticket_type_id, rank):
    pref = MagicMock()
    pref.user_id = user_id
    pref.ticket_type_id = ticket_type_id
    pref.rank = rank
    return pref


def make_mock_entry(id, campaign, user_id, status="pending"):
    entry = MagicMock()
    entry.id = id
    entry.campaign_id = campaign.id
    entry.campaign = campaign  # accessed directly, mirrors the real
    # selectinload(LotteryEntry.campaign) eager-load in the service
    entry.user_id = user_id
    entry.status = status
    return entry


def make_mock_db(concert=None, ticket_types=None, campaigns=None, preferences=None, entries=None):
    """Dispatches db.query(Model) on the model class — a plain
    MagicMock().query ignores call args and can't tell db.query(Concert)
    apart from db.query(TicketType) on its own, same idea as
    test_services.py's model_get_side_effect, adapted for the
    filter()/with_for_update()/options()/all() chains draw_lottery uses."""
    db = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        if model is Concert:
            q.filter.return_value.first.return_value = concert
        elif model is TicketType:
            q.filter.return_value.with_for_update.return_value.all.return_value = ticket_types or []
        elif model is LotteryCampaign:
            q.filter.return_value.with_for_update.return_value.all.return_value = campaigns or []
        elif model is LotteryPreference:
            q.filter.return_value.all.return_value = preferences or []
        elif model is LotteryEntry:
            q.filter.return_value.options.return_value.with_for_update.return_value.all.return_value = entries or []
        return q

    db.query.side_effect = query_side_effect
    return db


class _DeterministicRandom:
    """Stand-in for secrets.SystemRandom() that picks the first k
    candidates (in list order) instead of a random subset, so tests can
    assert exact winners/losers instead of just counts."""
    def sample(self, population, k):
        return list(population)[:k]


def _patched_random():
    return patch("app.services.lottery_draw_service.secrets.SystemRandom", return_value=_DeterministicRandom())


# ─────────────────────────────────────────────────────────────
# draw_lottery
# ─────────────────────────────────────────────────────────────

class TestDrawLottery:

    def test_single_preference_entries_under_capacity_all_win(self):
        from app.services.lottery_draw_service import draw_lottery

        vip_tt = make_mock_ticket_type(VIP_TT_ID, total_quantity=5, sold_quantity=0)
        campaign = make_mock_campaign(VIP_CAMPAIGN_ID, VIP_TT_ID)
        fan_ids = [uuid.uuid4() for _ in range(3)]
        prefs = [make_mock_preference(fid, VIP_TT_ID, rank=1) for fid in fan_ids]
        entries = [make_mock_entry(uuid.uuid4(), campaign, fid) for fid in fan_ids]

        db = make_mock_db(
            concert=make_mock_concert(),
            ticket_types=[vip_tt],
            campaigns=[campaign],
            preferences=prefs,
            entries=entries,
        )
        manager = make_mock_user(role="manager", company_id=COMPANY_ID)

        with _patched_random():
            draw_lottery(db, manager, CONCERT_ID)

        assert all(e.status == "won" for e in entries)
        assert vip_tt.sold_quantity == 3
        assert campaign.status == "drawn"
        assert db.add.call_count == 3

    def test_single_preference_entries_over_capacity_some_lose(self):
        from app.services.lottery_draw_service import draw_lottery

        vip_tt = make_mock_ticket_type(VIP_TT_ID, total_quantity=2, sold_quantity=0)
        campaign = make_mock_campaign(VIP_CAMPAIGN_ID, VIP_TT_ID)
        fan_ids = [uuid.uuid4() for _ in range(5)]
        prefs = [make_mock_preference(fid, VIP_TT_ID, rank=1) for fid in fan_ids]
        entries = [make_mock_entry(uuid.uuid4(), campaign, fid) for fid in fan_ids]

        db = make_mock_db(
            concert=make_mock_concert(),
            ticket_types=[vip_tt],
            campaigns=[campaign],
            preferences=prefs,
            entries=entries,
        )
        manager = make_mock_user(role="manager", company_id=COMPANY_ID)

        with _patched_random():
            draw_lottery(db, manager, CONCERT_ID)

        won = [e for e in entries if e.status == "won"]
        lost = [e for e in entries if e.status == "lost"]
        assert len(won) == 2
        assert len(lost) == 3
        assert vip_tt.sold_quantity == 2
        assert won == entries[:2]  # deterministic sampling picks the first k in list order

    def test_two_preferences_rank_cascade(self):
        """Fan Y wins their rank-1 tier (VIP); Fan X loses VIP at rank 1
        but rolls into their rank-2 tier (Premium) since they aren't in
        the won set yet — the exact scenario the rank-outer/tier-inner
        loop order exists to handle correctly."""
        from app.services.lottery_draw_service import draw_lottery

        vip_tt = make_mock_ticket_type(VIP_TT_ID, total_quantity=1, sold_quantity=0)
        premium_tt = make_mock_ticket_type(PREMIUM_TT_ID, total_quantity=1, sold_quantity=0)
        vip_campaign = make_mock_campaign(VIP_CAMPAIGN_ID, VIP_TT_ID)
        premium_campaign = make_mock_campaign(PREMIUM_CAMPAIGN_ID, PREMIUM_TT_ID)

        fan_x = uuid.uuid4()
        fan_y = uuid.uuid4()

        prefs = [
            make_mock_preference(fan_y, VIP_TT_ID, rank=1),
            make_mock_preference(fan_x, VIP_TT_ID, rank=1),
            make_mock_preference(fan_x, PREMIUM_TT_ID, rank=2),
        ]
        # Order matters — _DeterministicRandom picks the first k, so
        # listing fan_y's entry first means fan_y wins the VIP rank-1 draw.
        entry_y_vip = make_mock_entry(uuid.uuid4(), vip_campaign, fan_y)
        entry_x_vip = make_mock_entry(uuid.uuid4(), vip_campaign, fan_x)
        entry_x_premium = make_mock_entry(uuid.uuid4(), premium_campaign, fan_x)
        entries = [entry_y_vip, entry_x_vip, entry_x_premium]

        db = make_mock_db(
            concert=make_mock_concert(),
            ticket_types=[vip_tt, premium_tt],
            campaigns=[vip_campaign, premium_campaign],
            preferences=prefs,
            entries=entries,
        )
        manager = make_mock_user(role="manager", company_id=COMPANY_ID)

        with _patched_random():
            draw_lottery(db, manager, CONCERT_ID)

        assert entry_y_vip.status == "won"
        assert entry_x_vip.status == "lost"
        assert entry_x_premium.status == "won"
        assert vip_tt.sold_quantity == 1
        assert premium_tt.sold_quantity == 1

    def test_campaign_already_closed_is_a_no_op(self):
        from app.services.lottery_draw_service import draw_lottery

        db = make_mock_db(
            concert=make_mock_concert(),
            ticket_types=[make_mock_ticket_type(VIP_TT_ID)],
            campaigns=[],  # nothing with status == "open" left to draw
            preferences=[],
            entries=[],
        )
        manager = make_mock_user(role="manager", company_id=COMPANY_ID)

        result = draw_lottery(db, manager, CONCERT_ID)

        assert result == "no_open_campaigns"
        db.commit.assert_not_called()

    def test_entries_still_open_rejects_whole_draw(self):
        from app.services.lottery_draw_service import draw_lottery

        campaign = make_mock_campaign(VIP_CAMPAIGN_ID, VIP_TT_ID, entry_end_at=FUTURE)
        db = make_mock_db(
            concert=make_mock_concert(),
            ticket_types=[make_mock_ticket_type(VIP_TT_ID)],
            campaigns=[campaign],
            preferences=[],
            entries=[],
        )
        manager = make_mock_user(role="manager", company_id=COMPANY_ID)

        result = draw_lottery(db, manager, CONCERT_ID)

        assert result == "campaign_not_ended"
        assert campaign.status == "open"  # untouched
        db.commit.assert_not_called()

    def test_manager_from_other_company_is_forbidden(self):
        from app.services.lottery_draw_service import draw_lottery

        db = make_mock_db(
            concert=make_mock_concert(company_id=COMPANY_ID),
            ticket_types=[make_mock_ticket_type(VIP_TT_ID)],
            campaigns=[make_mock_campaign(VIP_CAMPAIGN_ID, VIP_TT_ID)],
            preferences=[],
            entries=[],
        )
        other_manager = make_mock_user(role="manager", company_id=OTHER_COMPANY_ID)

        result = draw_lottery(db, other_manager, CONCERT_ID)

        assert result == "forbidden"

    def test_fan_role_is_forbidden(self):
        """_user_scope_violation used to check `role == "user"` — a typo,
        since this project's roles are admin/manager/fan, so a fan was
        never actually rejected by this check. Now fixed to `role == "fan"`;
        this asserts the corrected behavior."""
        from app.services.lottery_draw_service import draw_lottery

        vip_tt = make_mock_ticket_type(VIP_TT_ID, total_quantity=1, sold_quantity=0)
        campaign = make_mock_campaign(VIP_CAMPAIGN_ID, VIP_TT_ID)
        db = make_mock_db(
            concert=make_mock_concert(),
            ticket_types=[vip_tt],
            campaigns=[campaign],
            preferences=[],
            entries=[],
        )
        fan = make_mock_user(role="fan", company_id=None)

        result = draw_lottery(db, fan, CONCERT_ID)

        assert result == "forbidden"

    def test_no_ticket_types_for_concert(self):
        from app.services.lottery_draw_service import draw_lottery

        db = make_mock_db(concert=make_mock_concert(), ticket_types=[], campaigns=[], preferences=[], entries=[])
        manager = make_mock_user(role="manager", company_id=COMPANY_ID)

        result = draw_lottery(db, manager, CONCERT_ID)

        assert result == "not_found"

    def test_concert_not_found(self):
        from app.services.lottery_draw_service import draw_lottery

        db = make_mock_db(concert=None)
        manager = make_mock_user(role="manager", company_id=COMPANY_ID)

        result = draw_lottery(db, manager, CONCERT_ID)

        assert result == "not_found"
