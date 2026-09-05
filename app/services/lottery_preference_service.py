import uuid
from sqlalchemy.orm import Session
from app.schema.lottery_preference import LotteryPreferenceSet
from app.db.models.lottery_preference import LotteryPreference
from app.db.models.ticket_type import TicketType
from app.db.models.concert import Concert
from app.db.models.user import Users
from app.exception.db_triggers import commit_or_raise

# Fan-facing, self-scoped by user_id = current_user.id — not company-scoped,
# since a fan (regardless of role) ranks their own tier preferences for a
# concert they want to attend. No require_manager_or_admin gate here; any
# authenticated user manages only their own rows (database-design.md §4's
# "own data" row for lottery_preferences/lottery_entries).
#
# set_preferences replaces the fan's whole ranked list for one concert in a
# single call rather than exposing rank-by-rank insert/update, since
# uq_lottery_preferences_rank/uq_lottery_preferences_tier make partial edits
# error-prone (swapping two ranks needs a temp value to avoid a UNIQUE clash
# mid-transaction). This mirrors how the draw job will read the list anyway:
# whole, in rank order.

def set_preferences(db: Session, data: LotteryPreferenceSet, current_user: Users):
    concert = db.get(Concert, data.concert_id)
    if not concert:
        return "not_found"
    seen = set()
    for tt_id in data.ticket_type_ids_in_order:
        if tt_id in seen:
            return "invalid"  # duplicate ticket_type_id in the ranked list
        seen.add(tt_id)
        tt = db.get(TicketType, tt_id)
        if not tt or tt.concert_id != data.concert_id:
            return "not_found"  # ticket type missing, or belongs to a different concert
    db.query(LotteryPreference).filter(
        LotteryPreference.concert_id == data.concert_id,
        LotteryPreference.user_id == current_user.id,
    ).delete()
    rows = []
    for i, tt_id in enumerate(data.ticket_type_ids_in_order, start=1):
        row = LotteryPreference(
            concert_id=data.concert_id, user_id=current_user.id, ticket_type_id=tt_id, rank=i,
        )
        db.add(row)
        rows.append(row)
    commit_or_raise(db)  # backstop for trg_lottery_preferences_ticket_type_concert
    for row in rows:
        db.refresh(row)
    return rows

def get_my_preferences(db: Session, concert_id: uuid.UUID, current_user: Users):
    result = (
        db.query(LotteryPreference)
        .filter(LotteryPreference.concert_id == concert_id, LotteryPreference.user_id == current_user.id)
        .order_by(LotteryPreference.rank)
        .all()
    )
    if not result:
        return False
    return result

def clear_my_preferences(db: Session, concert_id: uuid.UUID, current_user: Users):
    deleted = (
        db.query(LotteryPreference)
        .filter(LotteryPreference.concert_id == concert_id, LotteryPreference.user_id == current_user.id)
        .delete()
    )
    db.commit()
    return bool(deleted)
