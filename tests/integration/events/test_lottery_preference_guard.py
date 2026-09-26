import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.events import LotteryCampaign, LotteryEntry, LotteryPreference, TicketType
from app.exception.common import BadRequestError
from app.schema.events import LotteryPreferenceSet
from app.schema.events.lottery_campaign import CampaignStatus
from app.schema.events.lottery_entry import LotteryEntryStatus
from app.schema.events.ticket_type import SaleMethod, TicketTier
from app.services.events.lottery_preference_service import LotteryPreferenceService
from tests.integration._concurrency import db_session
from tests.integration.events.test_lottery_concurrency import (
    cleanup_concert_scenario,
    create_concert,
    create_fan,
    create_management_company,
    create_venue,
)

# A fan's ranking must stay usable by the draw: it can't change once entries close (or while a draw
# is running), and a tier the fan has applied to can't be removed from it.

HOLD_SECONDS = 1.0

# (company_id, venue_id, [user_id]) per _seed() call. The integration DB is shared across the run,
# so leftovers would show up in other suites (e.g. the "no companies" list test).
_seeded: list[tuple] = []


@pytest.fixture(autouse=True)
def cleanup_seeded_rows():
    yield
    while _seeded:
        cleanup_concert_scenario(*_seeded.pop())


def _lottery_tier(concert_id, tier):
    with db_session() as db:
        tt = TicketType(concert_id=concert_id, tier=tier, price=100, total_quantity=10, sale_method=SaleMethod.lottery)
        db.add(tt)
        db.commit()
        db.refresh(tt)
        return tt


def _seed(entry_end_at=None):
    """Concert with two lottery tiers A and B, each with an open campaign; the fan ranked [A, B]
    and applied to A."""
    company = create_management_company()
    venue = create_venue()
    concert = create_concert(company.id, venue.id)
    tier_a = _lottery_tier(concert.id, TicketTier.vip)
    tier_b = _lottery_tier(concert.id, TicketTier.regular)
    fan = create_fan()
    _seeded.append((company.id, venue.id, [fan.id]))
    now = datetime.now(timezone.utc)
    with db_session() as db:
        campaigns = [
            LotteryCampaign(ticket_type_id=tt.id, entry_start_at=now - timedelta(days=2),
                            entry_end_at=entry_end_at or now + timedelta(days=1), status=CampaignStatus.open)
            for tt in (tier_a, tier_b)
        ]
        db.add_all(campaigns)
        db.add_all([
            LotteryPreference(concert_id=concert.id, user_id=fan.id, ticket_type_id=tier_a.id, rank=1),
            LotteryPreference(concert_id=concert.id, user_id=fan.id, ticket_type_id=tier_b.id, rank=2),
        ])
        db.flush()
        db.add(LotteryEntry(campaign_id=campaigns[0].id, user_id=fan.id, status=LotteryEntryStatus.pending))
        db.commit()
        return concert.id, tier_a.id, tier_b.id, campaigns[0].id, fan


def _set(concert_id, tier_ids, fan):
    with db_session() as db:
        return LotteryPreferenceService.set_preferences(
            db, LotteryPreferenceSet(concert_id=concert_id, ticket_type_ids_in_order=list(tier_ids)), fan
        )


def _ranking(concert_id, fan):
    with db_session() as db:
        rows = (
            db.query(LotteryPreference)
            .filter(LotteryPreference.concert_id == concert_id, LotteryPreference.user_id == fan.id)
            .order_by(LotteryPreference.rank)
            .all()
        )
        return [row.ticket_type_id for row in rows]


def test_reorder_while_entries_open_succeeds():
    concert_id, tier_a, tier_b, _, fan = _seed()
    _set(concert_id, [tier_b, tier_a], fan)
    assert _ranking(concert_id, fan) == [tier_b, tier_a]


def test_dropping_an_applied_tier_is_rejected_and_ranking_kept():
    concert_id, tier_a, tier_b, _, fan = _seed()
    with pytest.raises(BadRequestError, match="already applied"):
        _set(concert_id, [tier_b], fan)
    assert _ranking(concert_id, fan) == [tier_a, tier_b]


def test_clear_with_an_applied_tier_is_rejected():
    concert_id, tier_a, tier_b, _, fan = _seed()
    with db_session() as db, pytest.raises(BadRequestError, match="already applied"):
        LotteryPreferenceService.clear_my_preferences(db, concert_id, fan)
    assert _ranking(concert_id, fan) == [tier_a, tier_b]


def test_change_after_entries_closed_is_rejected():
    concert_id, tier_a, tier_b, _, fan = _seed(entry_end_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    with pytest.raises(BadRequestError, match="have closed"):
        _set(concert_id, [tier_b, tier_a], fan)
    assert _ranking(concert_id, fan) == [tier_a, tier_b]


def test_change_waits_for_draw_lock_then_is_rejected():
    concert_id, tier_a, tier_b, campaign_a_id, fan = _seed()
    locked = threading.Event()

    def fake_draw():
        # Same lock the real draw takes on campaigns before it reads preferences.
        with db_session() as db:
            campaign = db.query(LotteryCampaign).filter(LotteryCampaign.id == campaign_a_id).with_for_update().one()
            locked.set()
            time.sleep(HOLD_SECONDS)
            campaign.status = CampaignStatus.drawn
            db.commit()

    drawer = threading.Thread(target=fake_draw)
    drawer.start()
    assert locked.wait(timeout=10)

    started = time.monotonic()
    with pytest.raises(BadRequestError, match="have closed"):
        _set(concert_id, [tier_b, tier_a], fan)
    waited = time.monotonic() - started
    drawer.join()

    assert waited >= HOLD_SECONDS * 0.8, f"ranking change didn't wait for the draw's lock ({waited:.2f}s)"
    assert _ranking(concert_id, fan) == [tier_a, tier_b]
