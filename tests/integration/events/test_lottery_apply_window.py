import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.events import LotteryCampaign, LotteryEntry, LotteryPreference
from app.exception.common import BadRequestError
from app.schema.events import LotteryEntryApply
from app.schema.events.lottery_campaign import CampaignStatus
from app.services.events.lottery_entry_service import LotteryEntryService
from tests.integration._concurrency import db_session
from tests.integration.events.test_lottery_concurrency import (
    cleanup_concert_scenario,
    create_concert,
    create_fan,
    create_management_company,
    create_ticket_type,
    create_venue,
)

# An apply racing a draw must never leave a pending entry on a drawn campaign: _stage_entry loads
# the campaign FOR SHARE, so it waits for the draw's FOR UPDATE lock and then sees status=drawn.

HOLD_SECONDS = 1.0

# (company_id, venue_id, [user_id]) per seed call. The integration DB is shared across the run,
# so leftovers would show up in other suites (e.g. the "no companies" list test).
_seeded: list[tuple] = []


@pytest.fixture(autouse=True)
def cleanup_seeded_rows():
    yield
    while _seeded:
        cleanup_concert_scenario(*_seeded.pop())


def _seed_open_campaign_with_ranked_fan():
    company = create_management_company()
    venue = create_venue()
    concert = create_concert(company.id, venue.id)
    ticket_type = create_ticket_type(concert.id, total_quantity=10)
    fan = create_fan()
    _seeded.append((company.id, venue.id, [fan.id]))
    now = datetime.now(timezone.utc)
    with db_session() as db:
        campaign = LotteryCampaign(
            ticket_type_id=ticket_type.id, entry_start_at=now - timedelta(days=1),
            entry_end_at=now + timedelta(days=1), status=CampaignStatus.open,
        )
        db.add(campaign)
        db.add(LotteryPreference(concert_id=concert.id, user_id=fan.id, ticket_type_id=ticket_type.id, rank=1))
        db.commit()
        db.refresh(campaign)
        return campaign.id, fan


def _apply(campaign_id: uuid.UUID, fan) -> None:
    with db_session() as db:
        LotteryEntryService.apply_to_lottery(db, LotteryEntryApply(campaign_id=campaign_id), fan)


def test_apply_waits_for_draw_lock_then_is_rejected():
    campaign_id, fan = _seed_open_campaign_with_ranked_fan()
    locked = threading.Event()

    def fake_draw():
        # Same lock the real draw takes on campaigns, held while it "draws".
        with db_session() as db:
            campaign = db.query(LotteryCampaign).filter(LotteryCampaign.id == campaign_id).with_for_update().one()
            locked.set()
            time.sleep(HOLD_SECONDS)
            campaign.status = CampaignStatus.drawn
            db.commit()

    drawer = threading.Thread(target=fake_draw)
    drawer.start()
    assert locked.wait(timeout=10)

    started = time.monotonic()
    with pytest.raises(BadRequestError, match="no longer accepting"):
        _apply(campaign_id, fan)
    waited = time.monotonic() - started
    drawer.join()

    # It blocked on the draw's lock (instead of reading the stale "open" row and inserting).
    assert waited >= HOLD_SECONDS * 0.8, f"apply didn't wait for the draw's lock ({waited:.2f}s)"
    with db_session() as db:
        assert db.query(LotteryEntry).filter(LotteryEntry.campaign_id == campaign_id).count() == 0


def test_apply_inside_open_window_succeeds():
    campaign_id, fan = _seed_open_campaign_with_ranked_fan()
    _apply(campaign_id, fan)
    with db_session() as db:
        assert db.query(LotteryEntry).filter(LotteryEntry.campaign_id == campaign_id).count() == 1


def test_apply_after_window_closed_is_rejected():
    campaign_id, fan = _seed_open_campaign_with_ranked_fan()
    with db_session() as db:
        campaign = db.get(LotteryCampaign, campaign_id)
        campaign.entry_start_at = datetime.now(timezone.utc) - timedelta(days=2)
        campaign.entry_end_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    with pytest.raises(BadRequestError, match="have closed"):
        _apply(campaign_id, fan)
