import uuid
from datetime import datetime, timedelta, timezone

from app.db.models.events import Concert, LotteryCampaign, LotteryEntry, LotteryPreference, Ticket, TicketType, Venue
from app.db.models.identity import Users
from app.db.models.talent import ManagementCompany
from app.exception.common import BadRequestError
from app.schema.events.lottery_campaign import CampaignStatus
from app.schema.events.lottery_entry import LotteryEntryStatus
from app.schema.events.ticket_type import SaleMethod, TicketTier
from app.services.events.lottery_draw_service import LotteryDrawService
from app.utils.hashing import hash_password
from tests.integration._concurrency import db_session, run_concurrently

# ───────────────────────────────────────────────────────────────
# What this file is for (see lottery_draw_service.draw_lottery,
# app/services/events/lottery_draw_service.py:39,43,51 — ticket_types,
# campaigns, and entries are all locked with with_for_update() before the
# draw math runs, and campaign.status flips to `drawn` right before commit,
# line 124-128). This proves that lock actually stops the same concert being
# drawn twice, not just that a single draw works.
#
# Calling the service directly, not going through HTTP: the router endpoint
# (app/router/events/concert.py:164-183, POST /concerts/{id}/draw-lottery)
# just enqueues a Celery task and returns immediately — two HTTP calls would
# race Celery's scheduling, not draw_lottery's own locking, and would need a
# real worker consuming a real broker to mean anything. Calling
# LotteryDrawService.draw_lottery directly, once per thread with its own
# Session, is what actually exercises the with_for_update() contention.
#
# test_concurrent_draw_only_succeeds_once races 2 concurrent draw_lottery
# calls for the SAME concert_id. Exactly one outcome should succeed (returns
# a LotteryResult) and the other should raise BadRequestError("No open
# lottery campaigns for this concert") — the losing thread's
# with_for_update() query only unblocks after the winner commits
# campaign.status = drawn, so its own `status == open` filter then excludes
# it. Post-condition checks after the race: sold_quantity never exceeds
# total_quantity, count_tickets(...) == sold_quantity, and count_won_entries
# matches sold_quantity too (no LotteryEntry double-won).
# ───────────────────────────────────────────────────────────────


# ───────────────────────────────────────────────────────────────
# Seed helpers — direct DB writes via db_session(), same sessionmaker the
# app itself uses. Building the full company -> venue -> concert ->
# ticket_type -> campaign -> entries chain by hand instead of through the
# admin/manager API because that's a lot of authenticated round-trips for a
# concurrency test whose actual target is draw_lottery's locking, not concert
# creation (covered elsewhere: test_venues.py and friends).
# ───────────────────────────────────────────────────────────────

def create_admin() -> Users:
    with db_session() as db:
        admin = Users(
            name="Admin", email=f"admin-{uuid.uuid4()}@example.com",
            hashed_password=hash_password("adminpass123"), role="admin", is_verified=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        return admin


def create_fan(email: str | None = None) -> Users:
    with db_session() as db:
        fan = Users(
            name="Racer", email=email or f"racer-{uuid.uuid4()}@example.com",
            hashed_password=hash_password("racerpass123"), role="fan", is_verified=True,
        )
        db.add(fan)
        db.commit()
        db.refresh(fan)
        return fan


def create_management_company() -> ManagementCompany:
    with db_session() as db:
        company = ManagementCompany(name=f"company-{uuid.uuid4()}")
        db.add(company)
        db.commit()
        db.refresh(company)
        return company


def create_venue() -> Venue:
    with db_session() as db:
        venue = Venue(name=f"venue-{uuid.uuid4()}", address="1 Test St", city="Tokyo", country="Japan", total_capacity=10000)
        db.add(venue)
        db.commit()
        db.refresh(venue)
        return venue


def create_concert(company_id: uuid.UUID, venue_id: uuid.UUID) -> Concert:
    with db_session() as db:
        concert = Concert(
            company_id=company_id, venue_id=venue_id, title=f"concert-{uuid.uuid4()}",
            capacity=100, event_datetime=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(concert)
        db.commit()
        db.refresh(concert)
        return concert


def create_ticket_type(concert_id: uuid.UUID, total_quantity: int) -> TicketType:
    with db_session() as db:
        ticket_type = TicketType(
            concert_id=concert_id, tier=TicketTier.regular, price=100, total_quantity=total_quantity,
            sale_method=SaleMethod.lottery,
        )
        db.add(ticket_type)
        db.commit()
        db.refresh(ticket_type)
        return ticket_type


def create_open_campaign(ticket_type_id: uuid.UUID) -> LotteryCampaign:
    """entry_end_at is already in the past — draw_lottery raises
    BadRequestError if any of a concert's campaigns hasn't ended yet
    (lottery_draw_service.py:47-48), so a real test needs this pre-closed."""
    with db_session() as db:
        now = datetime.now(timezone.utc)
        campaign = LotteryCampaign(
            ticket_type_id=ticket_type_id, entry_start_at=now - timedelta(days=2), entry_end_at=now - timedelta(hours=1),
            status=CampaignStatus.open,
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)
        return campaign


def create_entry_with_preference(concert_id: uuid.UUID, campaign_id: uuid.UUID, ticket_type_id: uuid.UUID, user_id: uuid.UUID, rank: int = 1) -> LotteryEntry:
    with db_session() as db:
        # Two flushes, not one: fn_require_lottery_preference (a DB trigger on
        # lottery_entries) checks for an existing lottery_preferences row at
        # INSERT time, and SQLAlchemy's unit-of-work doesn't know these two
        # inserts are order-dependent (no FK between them at the ORM level) —
        # committing both in one flush let it emit the entry insert first.
        db.add(LotteryPreference(concert_id=concert_id, user_id=user_id, ticket_type_id=ticket_type_id, rank=rank))
        db.flush()
        entry = LotteryEntry(campaign_id=campaign_id, user_id=user_id, status=LotteryEntryStatus.pending)
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry


def make_draw_call(concert_id: uuid.UUID, admin_id: uuid.UUID):
    """Zero-arg callable for run_concurrently — each call opens its OWN
    Session (and re-fetches the admin row in it), since a Session/ORM
    instance can't safely be shared across threads."""
    def _draw():
        with db_session() as db:
            current_user = db.get(Users, admin_id)
            return LotteryDrawService.draw_lottery(db, current_user, concert_id)
    return _draw


def get_ticket_type(ticket_type_id: uuid.UUID) -> TicketType:
    with db_session() as db:
        return db.get(TicketType, ticket_type_id)


def count_tickets(ticket_type_id: uuid.UUID) -> int:
    with db_session() as db:
        return db.query(Ticket).filter(Ticket.ticket_type_id == ticket_type_id).count()


def count_won_entries(campaign_id: uuid.UUID) -> int:
    with db_session() as db:
        return db.query(LotteryEntry).filter(LotteryEntry.campaign_id == campaign_id, LotteryEntry.status == LotteryEntryStatus.won).count()


# ───────────────────────────────────────────────────────────────
# Scenario builder — wires the seed helpers above into one ready-to-race
# concert. Adjust entrant_count / total_quantity per test as needed.
# ───────────────────────────────────────────────────────────────

def build_drawable_concert(total_quantity: int, entrant_count: int):
    admin = create_admin()
    company = create_management_company()
    venue = create_venue()
    concert = create_concert(company.id, venue.id)
    ticket_type = create_ticket_type(concert.id, total_quantity=total_quantity)
    campaign = create_open_campaign(ticket_type.id)
    fan_ids = []
    for _ in range(entrant_count):
        fan = create_fan()
        create_entry_with_preference(concert.id, campaign.id, ticket_type.id, fan.id)
        fan_ids.append(fan.id)
    return admin, company, venue, concert, ticket_type, campaign, fan_ids


# This suite shares one DB across the whole integration run — no per-test
# rollback (see tests/integration/conftest.py) — so anything seeded here
# that's left behind is visible to every test that runs after it (this
# already broke test_management_companies.py::test_list_companies_empty the
# first time this file ran without cleanup). Deletes cascade: company ->
# concert -> {ticket_type -> {campaign -> entry, ticket}}, and concert ->
# preference directly (all ON DELETE CASCADE) — so deleting the company, the
# venue, and every Users row this scenario created removes everything.

def cleanup_concert_scenario(company_id: uuid.UUID, venue_id: uuid.UUID, user_ids: list[uuid.UUID]) -> None:
    with db_session() as db:
        db.query(ManagementCompany).filter(ManagementCompany.id == company_id).delete()
        db.query(Venue).filter(Venue.id == venue_id).delete()
        db.query(Users).filter(Users.id.in_(user_ids)).delete(synchronize_session=False)
        db.commit()


def test_concurrent_draw_only_succeeds_once():
    admin, company, venue, concert, ticket_type, campaign, fan_ids = build_drawable_concert(total_quantity=1, entrant_count=3)
    draw_calls = [make_draw_call(concert.id, admin.id) for _ in range(2)]

    try:
        outcomes = run_concurrently(draw_calls)

        # make_draw_call's _draw() calls LotteryDrawService.draw_lottery
        # directly (not over HTTP) — it returns a LotteryResult or raises,
        # there's no response/status_code here. The losing thread's
        # with_for_update() query only unblocks after the winner commits
        # campaign.status = drawn, so its own `status == open` filter then
        # excludes it and it raises BadRequestError instead of returning a
        # result.
        successes = [o for o in outcomes if o.succeeded]
        failures = [o for o in outcomes if not o.succeeded]
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0].exception, BadRequestError)

        ticket_type_after = get_ticket_type(ticket_type.id)
        assert ticket_type_after.sold_quantity <= ticket_type_after.total_quantity
        assert count_tickets(ticket_type.id) == ticket_type_after.sold_quantity
        assert count_won_entries(campaign.id) == ticket_type_after.sold_quantity
    finally:
        cleanup_concert_scenario(company.id, venue.id, fan_ids + [admin.id])