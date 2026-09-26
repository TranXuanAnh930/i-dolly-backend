import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.exception.db_triggers import DuplicateConcertTicketError

DEFAULT_ID = uuid.uuid4()
SERVICE = "app.services.events.ticket_service"


def make_fan():
    user = MagicMock()
    user.id = DEFAULT_ID
    user.role = "fan"
    user.email = "fan@example.com"
    return user


def make_ticket_type(sale_method="direct"):
    tt = MagicMock()
    tt.id = DEFAULT_ID
    tt.concert_id = DEFAULT_ID
    tt.sale_method = sale_method
    tt.price = 1000
    tt.sold_quantity = 0
    tt.total_quantity = 10
    tt.tier = "regular"
    return tt


def make_db(ticket_type, ticket=None):
    from app.db.models.events import DirectSaleCampaign, Ticket, TicketType
    from app.db.models.marketplace import Payment

    db = MagicMock()
    queries = {model: MagicMock() for model in (Payment, TicketType, DirectSaleCampaign, Ticket)}
    queries[Payment].filter.return_value.first.return_value = None  # idempotency key unused
    queries[TicketType].filter.return_value.with_for_update.return_value.first.return_value = ticket_type
    queries[DirectSaleCampaign].filter.return_value.first.return_value = MagicMock()  # on sale
    queries[Ticket].filter.return_value.with_for_update.return_value.first.return_value = ticket
    db.query.side_effect = lambda model: queries.get(model, MagicMock())
    db.get.return_value = make_fan()
    return db


def successful_payment(db, user_id, ticket, data):
    ticket.status = "paid"
    payment = MagicMock()
    payment.status = "success"
    return payment


class TestConfirmationEmailAfterCommit:
    """The confirmation email is sent only once the commit succeeded."""

    def _checkout_direct(self, db, commit):
        from app.schema.events import TicketCheckoutCreate
        from app.services.events.ticket_service import TicketService

        data = TicketCheckoutCreate(ticket_type_id=DEFAULT_ID, amount=1100, gateway="mock", simulate_succ=True,
                                    idempotency_key=uuid.uuid4())
        with patch(f"{SERVICE}.PaymentService.create_ticket_payment", side_effect=successful_payment), \
             patch(f"{SERVICE}.TicketService._existing_live_ticket", return_value=None), \
             patch(f"{SERVICE}.TicketService._unresolved_lottery_entry", return_value=None), \
             patch(f"{SERVICE}.NotificationService.create_notification"), \
             patch(f"{SERVICE}.CacheInvalidation"), \
             patch(f"{SERVICE}.flush_or_raise"), \
             patch(f"{SERVICE}.commit_or_raise", side_effect=commit) as commit_mock, \
             patch(f"{SERVICE}.celery_app") as celery:
            calls = MagicMock()
            calls.attach_mock(commit_mock, "commit")
            calls.attach_mock(celery.send_task, "send_email")
            try:
                TicketService.checkout_ticket(db, DEFAULT_ID, data)
            finally:
                self.order = [c[0] for c in calls.mock_calls]
            return celery

    def test_direct_checkout_sends_email_after_commit(self):
        self._checkout_direct(make_db(make_ticket_type()), commit=None)
        assert self.order == ["commit", "send_email"]

    def test_direct_checkout_failed_commit_sends_nothing(self):
        with pytest.raises(DuplicateConcertTicketError):
            self._checkout_direct(make_db(make_ticket_type()), commit=DuplicateConcertTicketError("dup"))
        assert "send_email" not in self.order

    def _checkout_won(self, db, commit):
        from app.schema.events import WonTicketCheckoutCreate
        from app.services.events.ticket_service import TicketService

        data = WonTicketCheckoutCreate(amount=1100, gateway="mock", simulate_succ=True, idempotency_key=uuid.uuid4())
        with patch(f"{SERVICE}.PaymentService.create_ticket_payment", side_effect=successful_payment), \
             patch(f"{SERVICE}.NotificationService.create_notification"), \
             patch(f"{SERVICE}.commit_or_raise", side_effect=commit) as commit_mock, \
             patch(f"{SERVICE}.celery_app") as celery:
            calls = MagicMock()
            calls.attach_mock(commit_mock, "commit")
            calls.attach_mock(celery.send_task, "send_email")
            try:
                TicketService.checkout_won_ticket(db, DEFAULT_ID, DEFAULT_ID, data)
            finally:
                self.order = [c[0] for c in calls.mock_calls]

    def _won_ticket(self):
        ticket = MagicMock()
        ticket.id = DEFAULT_ID
        ticket.user_id = DEFAULT_ID
        ticket.status = "pending_payment"
        ticket.payment_deadline_at = datetime.now(timezone.utc) + timedelta(hours=1)
        return ticket

    def test_won_ticket_checkout_sends_email_after_commit(self):
        self._checkout_won(make_db(make_ticket_type("lottery"), ticket=self._won_ticket()), commit=None)
        assert self.order == ["commit", "send_email"]

    def test_won_ticket_checkout_failed_commit_sends_nothing(self):
        with pytest.raises(DuplicateConcertTicketError):
            self._checkout_won(make_db(make_ticket_type("lottery"), ticket=self._won_ticket()),
                               commit=DuplicateConcertTicketError("dup"))
        assert "send_email" not in self.order
