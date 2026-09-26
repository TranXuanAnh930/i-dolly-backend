import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.db.models.events import DirectSaleCampaign, Ticket, TicketType
from app.exception.checkout import InsufficientTicketStockError
from app.exception.db_triggers import DuplicateConcertTicketError, DuplicateIdempotencyKeyError
from app.schema.events import TicketCheckoutCreate
from app.schema.events.direct_sale_campaign import DirectSaleCampaignStatus
from app.schema.events.ticket import TicketStatus
from app.schema.events.ticket_type import SaleMethod, TicketTier
from app.services.events.ticket_service import TicketService
from app.utils.tax import with_tax
from tests.integration._concurrency import db_session, run_concurrently
from tests.integration.events.test_lottery_concurrency import (
    cleanup_concert_scenario,
    create_concert,
    create_fan,
    create_management_company,
    create_venue,
)

# ───────────────────────────────────────────────────────────────
# Races TicketService.checkout_ticket (direct sale) against real Postgres.
# checkout_ticket locks the ticket_type row FOR UPDATE, then checks stock,
# the one-live-ticket-per-concert rule and the idempotency key before a single
# commit. These tests prove that holds when calls really overlap.
#
# Calls the service directly, one Session per thread, like the lottery race
# tests: it's the locking under test, not the HTTP layer. The mock gateway with
# simulate_succ=True makes each successful checkout end as `paid` in one call.
# ───────────────────────────────────────────────────────────────

PRICE = 100


@pytest.fixture(autouse=True)
def no_email_dispatch():
    # A successful checkout enqueues a confirmation email after commit; no broker here.
    with patch("app.celery_app.celery_app.send_task"):
        yield


# ───────────────────────────────────────────────────────────────
# Seed helpers
# ───────────────────────────────────────────────────────────────

def create_direct_ticket_type(concert_id: uuid.UUID, total_quantity: int, tier: TicketTier = TicketTier.regular) -> TicketType:
    """A direct-sale tier with an open DirectSaleCampaign covering now."""
    now = datetime.now(timezone.utc)
    with db_session() as db:
        ticket_type = TicketType(
            concert_id=concert_id, tier=tier, price=PRICE, total_quantity=total_quantity,
            sale_method=SaleMethod.direct,
        )
        db.add(ticket_type)
        db.flush()
        db.add(DirectSaleCampaign(
            ticket_type_id=ticket_type.id, sale_start_at=now - timedelta(days=1),
            sale_end_at=now + timedelta(days=1), status=DirectSaleCampaignStatus.open,
        ))
        db.commit()
        db.refresh(ticket_type)
        return ticket_type


class Scenario:
    """Seeds one company/venue/concert and remembers every row it created so
    the fixture can delete them — the integration DB is shared across the run
    (see test_lottery_concurrency.py's cleanup note)."""

    def __init__(self):
        self.company = create_management_company()
        self.venue = create_venue()
        self.concert = create_concert(self.company.id, self.venue.id)
        self.user_ids: list[uuid.UUID] = []

    def fan(self):
        fan = create_fan()
        self.user_ids.append(fan.id)
        return fan

    def direct_tier(self, total_quantity: int, tier: TicketTier = TicketTier.regular) -> TicketType:
        return create_direct_ticket_type(self.concert.id, total_quantity, tier)

    def cleanup(self) -> None:
        cleanup_concert_scenario(self.company.id, self.venue.id, self.user_ids)


@pytest.fixture
def scenario():
    s = Scenario()
    yield s
    s.cleanup()


# ───────────────────────────────────────────────────────────────
# Race + assertion helpers
# ───────────────────────────────────────────────────────────────

def make_checkout_call(user_id: uuid.UUID, ticket_type_id: uuid.UUID, idempotency_key: uuid.UUID | None = None):
    """Zero-arg callable for run_concurrently; each call opens its own Session."""
    data = TicketCheckoutCreate(
        ticket_type_id=ticket_type_id,
        amount=with_tax(float(PRICE)),
        gateway="mock",
        simulate_succ=True,
        idempotency_key=idempotency_key or uuid.uuid4(),
    )

    def _checkout():
        with db_session() as db:
            return TicketService.checkout_ticket(db, user_id, data)
    return _checkout


def get_sold_quantity(ticket_type_id: uuid.UUID) -> int:
    with db_session() as db:
        return db.get(TicketType, ticket_type_id).sold_quantity


def count_paid_tickets(ticket_type_id: uuid.UUID) -> int:
    with db_session() as db:
        return db.query(Ticket).filter(Ticket.ticket_type_id == ticket_type_id, Ticket.status == TicketStatus.paid).count()


def count_live_tickets_for_user(user_id: uuid.UUID, concert_id: uuid.UUID) -> int:
    with db_session() as db:
        return (
            db.query(Ticket)
            .join(TicketType, Ticket.ticket_type_id == TicketType.id)
            .filter(
                Ticket.user_id == user_id,
                TicketType.concert_id == concert_id,
                Ticket.status.in_((TicketStatus.reserved, TicketStatus.pending_payment, TicketStatus.paid, TicketStatus.used)),
            )
            .count()
        )


def test_last_seat_sold_once(scenario):
    """N fans race for a tier with one seat left: exactly one wins."""
    ticket_type = scenario.direct_tier(total_quantity=1)
    fans = [scenario.fan() for _ in range(4)]
    calls = [make_checkout_call(fan.id, ticket_type.id) for fan in fans]

    outcomes = run_concurrently(calls)
    successes = [o for o in outcomes if o.succeeded]
    failures = [o for o in outcomes if not o.succeeded]
    assert len(successes) == 1
    assert len(failures) == 3
    assert all(isinstance(o.exception, InsufficientTicketStockError) for o in failures)
    assert get_sold_quantity(ticket_type.id) == 1
    assert count_paid_tickets(ticket_type.id) == 1


def test_same_fan_same_tier_double_submit(scenario):
    """One fan submits twice (different idempotency keys) for the same tier."""
    ticket_type = scenario.direct_tier(total_quantity=10)
    fan = scenario.fan()
    calls = [make_checkout_call(fan.id, ticket_type.id) for _ in range(2)]

    outcomes = run_concurrently(calls)
    successes = [o for o in outcomes if o.succeeded]
    failures = [o for o in outcomes if not o.succeeded]
    assert len(successes) == 1
    assert len(failures) == 1
    assert all(isinstance(o.exception, DuplicateConcertTicketError) for o in failures)
    assert count_live_tickets_for_user(fan.id, scenario.concert.id) == 1


def test_same_fan_two_tiers_same_concert(scenario):
    """One fan buys two different tiers of one concert at once. Each call locks
    a different ticket_type row, so the row lock doesn't serialize them —
    only the service check and trg_tickets_one_per_concert stand in the way."""
    tier_a = scenario.direct_tier(total_quantity=10, tier=TicketTier.vip)
    tier_b = scenario.direct_tier(total_quantity=10, tier=TicketTier.regular)
    fan = scenario.fan()
    calls = [make_checkout_call(fan.id, tier_a.id), make_checkout_call(fan.id, tier_b.id)]

    outcomes = run_concurrently(calls)
    successes = [o for o in outcomes if o.succeeded]
    failures = [o for o in outcomes if not o.succeeded]
    assert len(successes) == 1
    assert len(failures) == 1
    assert all(isinstance(o.exception, DuplicateConcertTicketError) for o in failures)
    assert get_sold_quantity(tier_a.id) + get_sold_quantity(tier_b.id) == 1
    assert count_live_tickets_for_user(fan.id, scenario.concert.id) == 1


def test_same_idempotency_key_submitted_twice(scenario):
    """The same request (same idempotency key) arrives twice at once. The key
    check runs before any lock, so the unique constraint on
    payments.idempotency_key is what catches the second insert."""
    ticket_type = scenario.direct_tier(total_quantity=10)
    fan = scenario.fan()
    key = uuid.uuid4()
    calls = [make_checkout_call(fan.id, ticket_type.id, idempotency_key=key) for _ in range(2)]

    outcomes = run_concurrently(calls)
    successes = [o for o in outcomes if o.succeeded]
    failures = [o for o in outcomes if not o.succeeded]
    assert len(successes) == 1
    assert len(failures) == 1
    assert all(isinstance(o.exception, DuplicateIdempotencyKeyError) for o in failures)
    assert get_sold_quantity(ticket_type.id) == 1
