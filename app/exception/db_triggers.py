"""
Typed exceptions for this project's Postgres trigger-enforced business rules
(the 8 trigger functions documented in docs/database-design.md SS4/SS4.1-4.2),
plus a helper that translates the raw DBAPIError SQLAlchemy raises when one
of them fires into one of these types instead.

Why this exists: every one of these triggers is a deliberate BEFORE
INSERT/UPDATE `RAISE EXCEPTION` — a real business-rule rejection, not a bug
— but until now nothing translated that into a clean HTTP response. It
surfaced as a raw sqlalchemy.exc.DBAPIError, which FastAPI has no handler
for, so it fell through as an unstyled 500. This mirrors the existing
app/exception/checkout.py convention (raise in the service, catch in the
router, map to a status code) rather than introducing a different pattern —
see docs/architecture.md SS2's "two conventions coexist" note.

Usage in a service function that performs a trigger-covered write, in place
of a bare db.commit()/db.flush():

    from app.exception.db_triggers import commit_or_raise

    db.add(row)
    commit_or_raise(db)
    db.refresh(row)

Usage in the router — one line, since the status code travels with the
exception class:

    from app.exception.db_triggers import TriggerViolationError

    try:
        result = some_service_fn(db, ...)
    except TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
"""

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session


class TriggerViolationError(Exception):
    """Base class for a Postgres trigger's RAISE EXCEPTION, translated into
    something a router can catch and map to a clean HTTP status. Never
    raised directly — always one of the subclasses below, which carry the
    original Postgres message as their text."""
    status_code = 400


class FanOnlyPurchaseError(TriggerViolationError):
    """trg_cart_fan_only / trg_orders_fan_only / trg_lottery_entries_fan_only
    / trg_tickets_fan_only (fn_enforce_fan_only_purchase) — an admin/manager
    account attempted a fan-only action. An authorization failure, not a
    validation one, so this is the one trigger exception that isn't 400.

    Unlike every other class here, this one is also raised **directly** by
    service code (cart_service.add_to_cart, order_service.checkout) as the
    primary check — the trigger is the backstop, per database-design.md
    §4.1, but until now nothing implemented the primary check it's meant to
    back up. Both paths (a direct raise, or translate_trigger_error()
    catching the trigger firing) produce the same type, so a router only
    ever needs the one `except TriggerViolationError` clause either way."""
    status_code = 403


class LotteryPreferenceTicketTypeMismatchError(TriggerViolationError):
    """trg_lottery_preferences_ticket_type_concert
    (fn_require_ticket_type_matches_concert)."""


class ResaleCapExceededError(TriggerViolationError):
    """trg_orders_items_resale_cap (fn_enforce_resale_cap)."""


class DuplicateConcertTicketError(TriggerViolationError):
    """trg_tickets_one_per_concert (fn_enforce_one_ticket_per_concert)."""


class ProductDetailKindConflictError(TriggerViolationError):
    """trg_album_details_exclusive_kind / trg_lightstick_details_exclusive_kind
    (fn_enforce_single_product_detail_kind)."""


class LotteryEntryCapExceededError(TriggerViolationError):
    """trg_lottery_entries_cap (fn_enforce_lottery_entry_cap)."""


class LotteryPreferenceRequiredError(TriggerViolationError):
    """trg_lottery_entries_require_preference (fn_require_lottery_preference)."""


class ConcertTicketCapacityExceededError(TriggerViolationError):
    """trg_ticket_types_capacity (fn_enforce_concert_ticket_capacity)."""


# (message substring, exception class) pairs, matched against the raw
# Postgres error text. Each substring is chosen to be unique to one trigger
# function's RAISE EXCEPTION wording (see the grep-able "RAISE EXCEPTION"
# lines under alembic/versions/ for the exact source) — order doesn't
# matter since none of them overlap.
_MESSAGE_PATTERNS = [
    ("cannot participate in purchase activity", FanOnlyPurchaseError),
    ("not concert_id=", LotteryPreferenceTicketTypeMismatchError),
    ("anti-resale cap on product_id=", ResaleCapExceededError),
    ("only one ticket per person per concert", DuplicateConcertTicketError),
    ("already has a lightstick_details row", ProductDetailKindConflictError),
    ("already has an album_details row", ProductDetailKindConflictError),
    ("(max_entries_per_user=", LotteryEntryCapExceededError),
    ("has not ranked ticket_type_id=", LotteryPreferenceRequiredError),
    ("would exceed concerts.capacity", ConcertTicketCapacityExceededError),
]


def translate_trigger_error(exc: DBAPIError) -> TriggerViolationError | None:
    """
    Inspect a DBAPIError SQLAlchemy raised and, if its message matches one
    of this project's trigger functions, return the matching typed
    exception (constructed with the original Postgres message as its
    text). Returns None if this doesn't look like one of ours — a real
    constraint violation, a connection error, an actual bug — so the
    caller re-raises the original exception unchanged instead of silently
    mislabeling something unrelated as a clean business-rule 400.
    """
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
    """
    db.commit(), translating a Postgres trigger violation into a typed
    TriggerViolationError instead of letting a raw DBAPIError escape to the
    router as an unhandled 500. Rolls back on any DB error so the session
    is left usable, and re-raises the original exception unchanged if it
    doesn't match a known trigger — see translate_trigger_error.
    """
    try:
        db.commit()
    except DBAPIError as exc:
        _handle(db, exc)


def flush_or_raise(db: Session) -> None:
    """Same as commit_or_raise, but for a mid-transaction db.flush() — used
    where a service needs the row's generated id (e.g. order.id) before the
    transaction is ready to commit. See order_service.checkout()."""
    try:
        db.flush()
    except DBAPIError as exc:
        _handle(db, exc)
