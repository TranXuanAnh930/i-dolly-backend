import uuid

# Registers every model with SQLAlchemy; this worker doesn't import the routers that normally do.
import app.db.base  # noqa: F401
from app.celery_app import celery_app
from app.db.models.events import Concert
from app.db.models.identity import Users
from app.db.session import session
from app.services.events.concert_service import ConcertService
from app.services.events.lottery_draw_service import LotteryDrawService


@celery_app.task(name="app.tasks.lottery.draw_lottery")
def draw_lottery_task(concert_id: str, user_id: str) -> dict:
    db = session()
    try:
        current_user = db.get(Users, uuid.UUID(user_id))
        result = LotteryDrawService.draw_lottery(db, current_user, uuid.UUID(concert_id))
        # Celery's JSON result backend can't serialize a Pydantic model.
        return result.model_dump(mode="json")
    except Exception:
        db.rollback()
        concert = db.get(Concert, uuid.UUID(concert_id))
        if concert:
            ConcertService.notify_managers_of_draw_failure(db, concert)
        raise
    finally:
        db.close()