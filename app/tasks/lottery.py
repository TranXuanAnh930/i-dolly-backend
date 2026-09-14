import uuid

# Registers every model class against the SQLAlchemy mapper registry before
# any query runs in this process — see app/db/base.py's own comment. The
# live app never needs this (main.py's router imports pull in every model
# transitively), but this worker process only ever imports Users below, so
# without it, resolving Users' string-based relationships (e.g. "Cart")
# fails with "failed to locate a name" the moment a query touches them.
import app.db.base  # noqa: F401
from app.celery_app import celery_app
from app.db.models.user import Users
from app.db.session import session
from app.schema.lottery_result import LotteryResult
from app.services.lottery_draw_service import draw_lottery


@celery_app.task(name="app.tasks.lottery.draw_lottery")
def draw_lottery_task(concert_id: str, user_id: str) -> LotteryResult:
    db = session()
    try:
        current_user = db.get(Users, uuid.UUID(user_id))
        return draw_lottery(db, current_user, uuid.UUID(concert_id))
    finally:
        db.close()