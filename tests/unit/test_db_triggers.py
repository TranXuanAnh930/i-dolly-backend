from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import DBAPIError

from app.exception.db_triggers import (
    ConcertTicketCapacityExceededError,
    DuplicateConcertTicketError,
    DuplicateIdempotencyKeyError,
    DuplicateTicketTypeError,
    FanOnlyPurchaseError,
    LotteryEntryCapExceededError,
    LotteryPreferenceRequiredError,
    LotteryPreferenceTicketTypeMismatchError,
    ProductDetailKindConflictError,
    ResaleCapExceededError,
    commit_or_raise,
    flush_or_raise,
    translate_trigger_error,
)


def db_error(text: str, message_primary: str | None = None) -> DBAPIError:
    """A DBAPIError wrapping a psycopg-like error whose str() is the Postgres message."""
    orig = Exception(text)
    orig.diag = MagicMock(message_primary=message_primary)
    return DBAPIError("INSERT ...", {}, orig)


class TestTranslateTriggerError:
    @pytest.mark.parametrize(
        ("text", "exc_cls", "status"),
        [
            ("user role admin cannot participate in purchase activity", FanOnlyPurchaseError, 403),
            ("ticket_type_id=x belongs to concert_id=y, not concert_id=z", LotteryPreferenceTicketTypeMismatchError, 400),
            ("anti-resale cap on product_id=1 exceeded", ResaleCapExceededError, 400),
            ("only one ticket per person per concert", DuplicateConcertTicketError, 400),
            ("product 1 already has a merch_details row", ProductDetailKindConflictError, 400),
            ("product 1 already has an album_details row", ProductDetailKindConflictError, 400),
            ("entry cap reached (max_entries_per_user=2)", LotteryEntryCapExceededError, 400),
            ("user has not ranked ticket_type_id=1", LotteryPreferenceRequiredError, 400),
            ("ticket types would exceed concerts.capacity", ConcertTicketCapacityExceededError, 400),
            ('duplicate key value violates unique constraint "uq_payment_idempotency_key"', DuplicateIdempotencyKeyError, 409),
            ('duplicate key value violates unique constraint "uq_ticket_types_concert_tier_method"', DuplicateTicketTypeError, 400),
        ],
    )
    def test_known_patterns_map_to_typed_errors(self, text, exc_cls, status):
        translated = translate_trigger_error(db_error(text))
        assert type(translated) is exc_cls
        assert translated.status_code == status

    def test_prefers_diag_message_primary(self):
        translated = translate_trigger_error(db_error("ERROR: only one ticket per person per concert\nCONTEXT: ...", "  short message  "))
        assert str(translated) == "short message"

    def test_falls_back_to_full_text_without_diag(self):
        orig = Exception("only one ticket per person per concert")
        translated = translate_trigger_error(DBAPIError("INSERT ...", {}, orig))
        assert str(translated) == "only one ticket per person per concert"

    def test_unknown_error_returns_none(self):
        assert translate_trigger_error(db_error("connection reset by peer")) is None


class TestCommitAndFlushOrRaise:
    @pytest.mark.parametrize(("helper", "method"), [(commit_or_raise, "commit"), (flush_or_raise, "flush")])
    def test_success_passes_through(self, helper, method):
        db = MagicMock()
        helper(db)
        getattr(db, method).assert_called_once()
        db.rollback.assert_not_called()

    @pytest.mark.parametrize(("helper", "method"), [(commit_or_raise, "commit"), (flush_or_raise, "flush")])
    def test_known_violation_rolls_back_and_raises_typed(self, helper, method):
        db = MagicMock()
        original = db_error("anti-resale cap on product_id=1 exceeded")
        getattr(db, method).side_effect = original

        with pytest.raises(ResaleCapExceededError) as info:
            helper(db)
        db.rollback.assert_called_once()
        assert info.value.__cause__ is original

    @pytest.mark.parametrize(("helper", "method"), [(commit_or_raise, "commit"), (flush_or_raise, "flush")])
    def test_unknown_error_rolls_back_and_reraises_original(self, helper, method):
        db = MagicMock()
        original = db_error("deadlock detected")
        getattr(db, method).side_effect = original

        with pytest.raises(DBAPIError) as info:
            helper(db)
        db.rollback.assert_called_once()
        assert info.value is original
