import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.events import Concert, LotteryCampaign, LotteryEntry, LotteryPreference, TicketType
from app.db.models.identity import Users
from app.exception.common import BadRequestError, NotFoundError
from app.exception.db_triggers import commit_or_raise
from app.schema.events import LotteryPreferenceSet
from app.schema.events.lottery_campaign import CampaignStatus
from app.schema.events.lottery_entry import LotteryEntryStatus
from app.schema.events.ticket_type import SaleMethod


class LotteryPreferenceService:

    # Fan-facing: each user ranks their own tiers. set_preferences replaces the whole ranked list,
    # since the unique rank constraints make partial edits awkward.
    #
    # The draw looks up a preference for every pending entry, so a ranking must stay stable once
    # entries close, and a tier the fan has applied to can't be dropped from it.

    @staticmethod
    def _current_tier_ids(db: Session, concert_id: uuid.UUID, user_id: uuid.UUID) -> set[uuid.UUID]:
        rows = (
            db.query(LotteryPreference.ticket_type_id)
            .filter(LotteryPreference.concert_id == concert_id, LotteryPreference.user_id == user_id)
            .all()
        )
        return {tt_id for (tt_id,) in rows}

    @staticmethod
    def _campaigns_for_tiers(db: Session, tier_ids: set[uuid.UUID]) -> list[LotteryCampaign]:
        if not tier_ids:
            return []
        # FOR SHARE: the draw locks these campaigns FOR UPDATE before reading preferences, so an
        # edit either commits before the draw reads them or waits and then sees status=drawn.
        return (
            db.query(LotteryCampaign)
            .filter(LotteryCampaign.ticket_type_id.in_(tier_ids), LotteryCampaign.status != CampaignStatus.cancelled)
            .with_for_update(read=True)
            .populate_existing()
            .all()
        )

    @staticmethod
    def _entered_tier_ids(db: Session, tier_ids: set[uuid.UUID], user_id: uuid.UUID) -> set[uuid.UUID]:
        if not tier_ids:
            return set()
        rows = (
            db.query(LotteryCampaign.ticket_type_id)
            .join(LotteryEntry, LotteryEntry.campaign_id == LotteryCampaign.id)
            .filter(
                LotteryEntry.user_id == user_id,
                LotteryEntry.status == LotteryEntryStatus.pending,
                LotteryCampaign.ticket_type_id.in_(tier_ids),
            )
            .all()
        )
        return {tt_id for (tt_id,) in rows}

    @staticmethod
    def _check_ranking_change_allowed(
        db: Session, concert_id: uuid.UUID, user_id: uuid.UUID, new_tier_ids: set[uuid.UUID]
    ) -> None:
        """Raise if the fan's ranking can't be replaced with `new_tier_ids`.

        Every ranked tier must have a campaign that is open for entries. Campaigns of the current
        tiers are checked too, since removing a tier's preference affects the draw as much as adding
        one; a tier the fan has applied to can't be removed.
        """
        current_tier_ids = LotteryPreferenceService._current_tier_ids(db, concert_id, user_id)
        campaigns = LotteryPreferenceService._campaigns_for_tiers(db, current_tier_ids | new_tier_ids)
        now = datetime.now(timezone.utc)
        if any(c.status != CampaignStatus.open or now > c.entry_end_at for c in campaigns):
            raise BadRequestError("Lottery entries for this concert have closed, so your ranking can no longer change")

        campaigns_by_tier = {c.ticket_type_id: c for c in campaigns}
        for tier_id in new_tier_ids:
            campaign = campaigns_by_tier.get(tier_id)
            if campaign is None:
                raise NotFoundError("No lottery campaign found for this ticket type")
            if now < campaign.entry_start_at:
                raise BadRequestError("Entries for this lottery campaign haven't opened yet")

        removed_tier_ids = current_tier_ids - new_tier_ids
        if LotteryPreferenceService._entered_tier_ids(db, removed_tier_ids, user_id):
            raise BadRequestError("You can't remove a tier you've already applied to")

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

        LotteryPreferenceService._check_ranking_change_allowed(db, data.concert_id, current_user.id, seen)

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
        commit_or_raise(db)  # trg_lottery_preferences_ticket_type_concert
        for row in rows:
            db.refresh(row)
        return rows

    @staticmethod
    def get_my_preferences(db: Session, concert_id: uuid.UUID, current_user: Users) -> list[LotteryPreference]:
        return (
            db.query(LotteryPreference)
            .filter(LotteryPreference.concert_id == concert_id, LotteryPreference.user_id == current_user.id)
            .order_by(LotteryPreference.rank)
            .all()
        )

    @staticmethod
    def clear_my_preferences(db: Session, concert_id: uuid.UUID, current_user: Users) -> bool:
        # Clearing is replacing the ranking with an empty one.
        LotteryPreferenceService._check_ranking_change_allowed(db, concert_id, current_user.id, set())
        deleted = (
            db.query(LotteryPreference)
            .filter(LotteryPreference.concert_id == concert_id, LotteryPreference.user_id == current_user.id)
            .delete()
        )
        db.commit()
        return bool(deleted)
