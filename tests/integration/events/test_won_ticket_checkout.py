import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.db.models.events import Ticket, TicketType
from app.db.models.marketplace import Payment
from app.db.models.shared import Notification
from app.exception.checkout import PaymentAmountMismatch, TicketNotFoundError, TicketNotPayableError
from app.exception.db_triggers import DuplicateIdempotencyKeyError
from app.schema.events import WonTicketCheckoutCreate
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
# TicketService.checkout_won_ticket against real Postgres: paying for a ticket
# the lottery draw already issued. The draw counted the seat in sold_quantity,
# so a successful payment must leave it unchanged, and an expired deadline
# must release it exactly once, even when two requests race on the same
# ticket. Service called directly, one Session per call, as in
# test_ticket_checkout_concurrency.py.
# ───────────────────────────────────────────────────────────────

PRICE = 100
AMOUNT = with_tax(float(PRICE))


@pytest.fixture(autouse=True)
def no_email_dispatch():
    # A confirmed payment enqueues an email after commit; no broker here.
    with patch("app.celery_app.celery_app.send_task") as send_task:
        yield send_task


class Scenario:
    """One concert with a lottery tier whose single seat the draw already handed to a fan."""

    def __init__(self):
        self.company = create_management_company()
        self.venue = create_venue()
        self.concert = create_concert(self.company.id, self.venue.id)
        self.user_ids: list[uuid.UUID] = []

    def fan(self):
        fan = create_fan()
        self.user_ids.append(fan.id)
        return fan

    def ticket_type(self, sale_method: SaleMethod = SaleMethod.lottery, sold_quantity: int = 1) -> TicketType:
        with db_session() as db:
            ticket_type = TicketType(
                concert_id=self.concert.id, tier=TicketTier.regular, price=PRICE, total_quantity=5,
                sale_method=sale_method, sold_quantity=sold_quantity,
            )
            db.add(ticket_type)
            db.commit()
            db.refresh(ticket_type)
            return ticket_type

    def won_ticket(self, user_id, ticket_type_id, status=TicketStatus.pending_payment, deadline_delta=timedelta(days=1)) -> Ticket:
        with db_session() as db:
            ticket = Ticket(
                ticket_type_id=ticket_type_id, user_id=user_id, status=status,
                payment_deadline_at=datetime.now(timezone.utc) + deadline_delta if deadline_delta is not None else None,
            )
            db.add(ticket)
            db.commit()
            db.refresh(ticket)
            return ticket

    def cleanup(self) -> None:
        cleanup_concert_scenario(self.company.id, self.venue.id, self.user_ids)


@pytest.fixture
def scenario():
    s = Scenario()
    yield s
    s.cleanup()


def pay(user_id, ticket_id, amount=AMOUNT, simulate_succ=True, idempotency_key=None):
    data = WonTicketCheckoutCreate(
        amount=amount, gateway="mock", simulate_succ=simulate_succ, idempotency_key=idempotency_key or uuid.uuid4(),
    )
    with db_session() as db:
        return TicketService.checkout_won_ticket(db, user_id, ticket_id, data)


def make_pay_call(user_id, ticket_id, idempotency_key=None):
    return lambda: pay(user_id, ticket_id, idempotency_key=idempotency_key)


def reload(model, id_):
    with db_session() as db:
        return db.get(model, id_)


def payments_for(ticket_id) -> list[Payment]:
    with db_session() as db:
        return db.query(Payment).filter(Payment.ticket_id == ticket_id).all()


# ───────────────────────────────────────────────────────────────
# Sequential paths
# ───────────────────────────────────────────────────────────────

def test_successful_payment_marks_paid_without_touching_sold_quantity(scenario, no_email_dispatch):
    fan = scenario.fan()
    ticket_type = scenario.ticket_type()
    ticket = scenario.won_ticket(fan.id, ticket_type.id)

    result = pay(fan.id, ticket.id)

    assert result.status == TicketStatus.paid
    assert result.payment_id is not None
    assert reload(TicketType, ticket_type.id).sold_quantity == 1
    with db_session() as db:
        assert db.query(Notification).filter(Notification.ticket_id == ticket.id).count() == 1
    no_email_dispatch.assert_called_once()


def test_failed_mock_payment_keeps_ticket_payable(scenario, no_email_dispatch):
    """A declined lottery payment leaves the ticket pending so the fan can retry."""
    fan = scenario.fan()
    ticket_type = scenario.ticket_type()
    ticket = scenario.won_ticket(fan.id, ticket_type.id)

    result = pay(fan.id, ticket.id, simulate_succ=False)
    assert result.status == TicketStatus.pending_payment
    no_email_dispatch.assert_not_called()

    retried = pay(fan.id, ticket.id)
    assert retried.status == TicketStatus.paid
    assert len(payments_for(ticket.id)) == 2


def test_other_users_ticket_is_not_found(scenario):
    owner, other = scenario.fan(), scenario.fan()
    ticket_type = scenario.ticket_type()
    ticket = scenario.won_ticket(owner.id, ticket_type.id)

    with pytest.raises(TicketNotFoundError):
        pay(other.id, ticket.id)
    assert reload(Ticket, ticket.id).status == TicketStatus.pending_payment


def test_missing_ticket_is_not_found(scenario):
    with pytest.raises(TicketNotFoundError):
        pay(scenario.fan().id, uuid.uuid4())


def test_direct_sale_ticket_is_not_payable_here(scenario):
    fan = scenario.fan()
    ticket_type = scenario.ticket_type(sale_method=SaleMethod.direct)
    ticket = scenario.won_ticket(fan.id, ticket_type.id)

    with pytest.raises(TicketNotPayableError):
        pay(fan.id, ticket.id)


def test_already_paid_ticket_is_not_payable_again(scenario):
    fan = scenario.fan()
    ticket_type = scenario.ticket_type()
    ticket = scenario.won_ticket(fan.id, ticket_type.id, status=TicketStatus.paid)

    with pytest.raises(TicketNotPayableError):
        pay(fan.id, ticket.id)
    assert payments_for(ticket.id) == []


def test_past_deadline_expires_ticket_and_releases_seat(scenario):
    fan = scenario.fan()
    ticket_type = scenario.ticket_type(sold_quantity=1)
    ticket = scenario.won_ticket(fan.id, ticket_type.id, deadline_delta=timedelta(minutes=-1))

    with pytest.raises(TicketNotPayableError, match="deadline"):
        pay(fan.id, ticket.id)

    assert reload(Ticket, ticket.id).status == TicketStatus.expired
    assert reload(TicketType, ticket_type.id).sold_quantity == 0
    assert payments_for(ticket.id) == []


def test_no_deadline_is_payable(scenario):
    fan = scenario.fan()
    ticket_type = scenario.ticket_type()
    ticket = scenario.won_ticket(fan.id, ticket_type.id, deadline_delta=None)

    assert pay(fan.id, ticket.id).status == TicketStatus.paid


def test_amount_mismatch_rejected(scenario):
    fan = scenario.fan()
    ticket_type = scenario.ticket_type()
    ticket = scenario.won_ticket(fan.id, ticket_type.id)

    with pytest.raises(PaymentAmountMismatch):
        pay(fan.id, ticket.id, amount=AMOUNT + 1)
    assert reload(Ticket, ticket.id).status == TicketStatus.pending_payment


def test_reused_idempotency_key_rejected(scenario):
    fan = scenario.fan()
    ticket_type = scenario.ticket_type()
    first = scenario.won_ticket(fan.id, ticket_type.id, status=TicketStatus.pending_payment)
    key = uuid.uuid4()
    pay(fan.id, first.id, simulate_succ=False, idempotency_key=key)

    with pytest.raises(DuplicateIdempotencyKeyError):
        pay(fan.id, first.id, idempotency_key=key)


# ───────────────────────────────────────────────────────────────
# Races
# ───────────────────────────────────────────────────────────────

def test_double_submit_pays_once(scenario):
    """Two payments (different keys) for one won ticket: the ticket row lock makes the second see
    status=paid and refuse, so only one payment is recorded."""
    fan = scenario.fan()
    ticket_type = scenario.ticket_type()
    ticket = scenario.won_ticket(fan.id, ticket_type.id)

    outcomes = run_concurrently([make_pay_call(fan.id, ticket.id) for _ in range(2)])
    successes = [o for o in outcomes if o.succeeded]
    failures = [o for o in outcomes if not o.succeeded]

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0].exception, TicketNotPayableError)
    assert [p.status.value for p in payments_for(ticket.id)] == ["success"]
    assert reload(TicketType, ticket_type.id).sold_quantity == 1


def test_same_idempotency_key_submitted_twice(scenario):
    fan = scenario.fan()
    ticket_type = scenario.ticket_type()
    ticket = scenario.won_ticket(fan.id, ticket_type.id)
    key = uuid.uuid4()

    outcomes = run_concurrently([make_pay_call(fan.id, ticket.id, idempotency_key=key) for _ in range(2)])
    failures = [o for o in outcomes if not o.succeeded]

    assert sum(o.succeeded for o in outcomes) == 1
    assert isinstance(failures[0].exception, (DuplicateIdempotencyKeyError, TicketNotPayableError))
    assert len(payments_for(ticket.id)) == 1


def test_concurrent_attempts_past_deadline_release_seat_once(scenario):
    """Both racers find the deadline passed; the seat must be released once, not twice."""
    fan = scenario.fan()
    ticket_type = scenario.ticket_type(sold_quantity=1)
    ticket = scenario.won_ticket(fan.id, ticket_type.id, deadline_delta=timedelta(minutes=-1))

    outcomes = run_concurrently([make_pay_call(fan.id, ticket.id) for _ in range(3)])

    assert not any(o.succeeded for o in outcomes)
    assert all(isinstance(o.exception, TicketNotPayableError) for o in outcomes)
    assert reload(Ticket, ticket.id).status == TicketStatus.expired
    assert reload(TicketType, ticket_type.id).sold_quantity == 0
