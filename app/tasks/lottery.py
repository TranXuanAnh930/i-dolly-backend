import uuid

# Registers every model class against the SQLAlchemy mapper registry before
# any query runs in this process — see app/db/base.py's own comment. The
# live app never needs this (main.py's router imports pull in every model
# transitively), but this worker process only ever imports Users below, so
# without it, resolving Users' string-based relationships (e.g. "Cart")
# fails with "failed to locate a name" the moment a query touches them.
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
        # Celery's JSON result serializer only knows plain types — a raw
        # LotteryResult (Pydantic model) raised kombu.exceptions.EncodeError
        # here, which Celery logged as "Task ... raised unexpected" and
        # recorded as a FAILURE even though the draw itself had already
        # committed successfully (this happens in Celery's own result-store
        # step, after this function has already returned, so the except
        # block below never sees it — a different bug from anything that
        # block guards against).
        return result.model_dump(mode="json")
    except Exception:
        db.rollback()
        concert = db.get(Concert, uuid.UUID(concert_id))
        if concert:
            ConcertService.notify_managers_of_draw_failure(db, concert)
        raise
    finally:
        db.close()