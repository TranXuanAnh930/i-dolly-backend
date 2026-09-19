import uuid

from sqlalchemy.orm import Session

from app.db.models.events import Concert, LotteryPreference, TicketType
from app.db.models.identity import Users
from app.exception.common import BadRequestError, NotFoundError
from app.exception.db_triggers import commit_or_raise
from app.schema.events import LotteryPreferenceSet
from app.schema.events.ticket_type import SaleMethod


class LotteryPreferenceService:

    # Fan-facing, self-scoped by user_id — not company-scoped, since any authenticated user just
    # ranks their own preferences (database-design.md §4). set_preferences replaces the whole
    # ranked list in one call rather than rank-by-rank edits, since the rank/tier UNIQUE
    # constraints make partial edits error-prone (swapping two ranks needs a temp value).

    @staticmethod
    def set_preferences(db: Session, data: LotteryPreferenceSet, current_user: Users) -> list[LotteryPreference]:
        concert = db.get(Concert, data.concert_id)
        if not concert:
            raise NotFoundError("Concert or ticket type not found, or a ticket type doesn't belong to this concert")
        seen = set()
        for tt_id in data.ticket_type_ids_in_order:
            if tt_id in seen:
                raise BadRequestError("Duplicate ticket_type_id in the ranked list")
            seen.add(tt_id)
            tt = db.get(TicketType, tt_id)
            if not tt or tt.concert_id != data.concert_id:
                raise NotFoundError("Concert or ticket type not found, or a ticket type doesn't belong to this concert")
            if tt.sale_method != SaleMethod.lottery:
                raise BadRequestError("Can only rank lottery-sale ticket types")
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

    @staticmethod
    def get_my_preferences(db: Session, concert_id: uuid.UUID, current_user: Users) -> list[LotteryPreference] | None:
        result = (
            db.query(LotteryPreference)
            .filter(LotteryPreference.concert_id == concert_id, LotteryPreference.user_id == current_user.id)
            .order_by(LotteryPreference.rank)
            .all()
        )
        if not result:
            return None
        return result

    @staticmethod
    def clear_my_preferences(db: Session, concert_id: uuid.UUID, current_user: Users) -> bool:
        deleted = (
            db.query(LotteryPreference)
            .filter(LotteryPreference.concert_id == concert_id, LotteryPreference.user_id == current_user.id)
            .delete()
        )
        db.commit()
        return bool(deleted)
