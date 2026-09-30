"""Typed exceptions for business rules enforced by Postgres triggers and UNIQUE constraints.

commit_or_raise()/flush_or_raise() translate the raw DBAPIError raised when one of those rules
fires into a TriggerViolationError subclass that carries its own HTTP status code:

    db.add(row)
    commit_or_raise(db)

    # router
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
"""

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.exception.common import CodedError


class TriggerViolationError(CodedError):
    """Base class; only subclasses are raised, carrying the original Postgres message."""
    status_code = 400
    code = "rule_violation"


class FanOnlyPurchaseError(TriggerViolationError):
    """An admin/manager attempted a fan-only action (fn_enforce_fan_only_purchase triggers).

    Also raised directly by services as the primary check; the trigger is the backstop."""
    status_code = 403
    code = "fan_only_purchase"


class LotteryPreferenceTicketTypeMismatchError(TriggerViolationError):
    """trg_lottery_preferences_ticket_type_concert
    (fn_require_ticket_type_matches_concert)."""
    code = "ticket_type_concert_mismatch"


class ResaleCapExceededError(TriggerViolationError):
    """trg_orders_items_resale_cap (fn_enforce_resale_cap)."""
    code = "resale_cap_exceeded"


class DuplicateConcertTicketError(TriggerViolationError):
    """trg_tickets_one_per_concert (fn_enforce_one_ticket_per_concert)."""
    code = "duplicate_concert_ticket"


class ProductDetailKindConflictError(TriggerViolationError):
    """trg_album_details_exclusive_kind / trg_merch_details_exclusive_kind
    (fn_enforce_single_product_detail_kind)."""
    code = "product_detail_kind_conflict"


class LotteryEntryCapExceededError(TriggerViolationError):
    """trg_lottery_entries_cap (fn_enforce_lottery_entry_cap)."""
    code = "lottery_entry_cap_exceeded"


class LotteryPreferenceRequiredError(TriggerViolationError):
    """trg_lottery_entries_require_preference (fn_require_lottery_preference)."""
    code = "lottery_preference_required"


class ConcertTicketCapacityExceededError(TriggerViolationError):
    """trg_ticket_types_capacity (fn_enforce_concert_ticket_capacity)."""
    code = "concert_capacity_exceeded"


class DuplicateIdempotencyKeyError(TriggerViolationError):
    """uq_payment_idempotency_key: a checkout retried with an already-used idempotency key."""
    status_code = 409
    code = "duplicate_idempotency_key"


class DuplicateTicketTypeError(TriggerViolationError):
    """uq_ticket_types_concert_tier_method: one ticket type per (concert, tier, sale_method)."""
    code = "duplicate_ticket_type"


# (substring of the Postgres error text, exception class). Each substring matches exactly one
# trigger's RAISE EXCEPTION wording or constraint name, so order doesn't matter.
_MESSAGE_PATTERNS = [
    ("cannot participate in purchase activity", FanOnlyPurchaseError),
    ("not concert_id=", LotteryPreferenceTicketTypeMismatchError),
    ("anti-resale cap on product_id=", ResaleCapExceededError),
    ("only one ticket per person per concert", DuplicateConcertTicketError),
    ("already has a merch_details row", ProductDetailKindConflictError),
    ("already has an album_details row", ProductDetailKindConflictError),
    ("(max_entries_per_user=", LotteryEntryCapExceededError),
    ("has not ranked ticket_type_id=", LotteryPreferenceRequiredError),
    ("would exceed concerts.capacity", ConcertTicketCapacityExceededError),
    ("uq_payment_idempotency_key", DuplicateIdempotencyKeyError),
    ("uq_ticket_types_concert_tier_method", DuplicateTicketTypeError),
]


def translate_trigger_error(exc: DBAPIError) -> TriggerViolationError | None:
    """Return the typed exception matching this DB error, or None if it isn't a known rule
    violation (the caller then re-raises the original error unchanged)."""
    orig = getattr(exc, "orig", None)
    text = str(orig) if orig is not None else str(exc)
    for pattern, exc_cls in _MESSAGE_PATTERNS:
        if pattern in text:
            diag = getattr(orig, "diag", None)
            message = (getattr(diag, "message_primary", None) or text).strip()
            return exc_cls(message)
    return None


def _handle(db: Session, exc: DBAPIError) -> None:
    db.rollback()
    translated = translate_trigger_error(exc)
    if translated is not None:
        raise translated from exc
    raise


def commit_or_raise(db: Session) -> None:
    """db.commit(), raising a TriggerViolationError for known rule violations.

    Rolls back on any DB error; unknown errors are re-raised unchanged."""
    try:
        db.commit()
    except DBAPIError as exc:
        _handle(db, exc)


def flush_or_raise(db: Session) -> None:
    """commit_or_raise for a mid-transaction db.flush() (e.g. to get a generated id)."""
    try:
        db.flush()
    except DBAPIError as exc:
        _handle(db, exc)
