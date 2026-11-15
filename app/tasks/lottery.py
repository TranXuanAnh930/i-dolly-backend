import logging
import uuid

from sqlalchemy.orm import Session

# Registers every model with SQLAlchemy; this worker doesn't import the routers that normally do.
import app.db.base  # noqa: F401
from app.cache.invalidation import CacheInvalidation
from app.celery_app import celery_app
from app.db.models.events import Concert
from app.db.models.identity import Users
from app.db.session import session
from app.services.events.concert_service import ConcertService
from app.services.events.lottery_draw_service import LotteryDrawService

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.lottery.draw_lottery")
def draw_lottery_task(concert_id: str, user_id: str) -> dict:
    concert_uuid = uuid.UUID(concert_id)
    db = session()
    try:
        try:
            current_user = db.get(Users, uuid.UUID(user_id))
            result = LotteryDrawService.draw_lottery(db, current_user, concert_uuid)
        except Exception:
            db.rollback()
            try:
                concert = db.get(Concert, concert_uuid)
                if concert:
                    ConcertService.notify_managers_of_draw_failure(db, concert)
            except Exception:
                logger.exception("draw %s: failed to notify managers of draw failure", concert_uuid)
            raise

        _after_draw(db, concert_uuid)
        # Celery's JSON result backend can't serialize a Pydantic model.
        return result.model_dump(mode="json")

    finally:
        db.close()


def _after_draw(db: Session, concert_id: uuid.UUID) -> None:
    # The draw is committed: these steps are best-effort and must never turn it into a failure, so
    # each catches everything on its own. No rollback after a failed notification: the session is
    # closed right after and nothing else uses it.
    try:
        CacheInvalidation.delete_cached_concert_detail(concert_id)
    except Exception:
        logger.exception("draw %s: cache invalidation failed", concert_id)
    try:
        concert = db.get(Concert, concert_id)
        ConcertService.notify_managers_of_draw_completion(db, concert)
    except Exception:
        logger.exception("draw %s: completion notification failed", concert_id)
