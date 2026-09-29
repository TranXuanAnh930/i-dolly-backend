import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.tasks.email import send_email as send_email_task
from app.tasks.example import ping
from app.tasks.lottery import draw_lottery_task

# Celery tasks are called synchronously here (task(...) runs the body in-process); no broker
# or worker is involved.

LOTTERY = "app.tasks.lottery"


class TestPing:
    def test_returns_pong(self):
        assert ping() == "pong"


class TestSendEmailTask:
    def test_delegates_to_email_sender(self):
        with patch("app.tasks.email.deliver_email") as deliver:
            send_email_task("fan@example.com", "Subject", "<p>Body</p>")
        deliver.assert_called_once_with("fan@example.com", "Subject", "<p>Body</p>")


class TestDrawLotteryTask:
    def _db(self, user=None, concert=None):
        db = MagicMock()
        db.get.side_effect = lambda model, _id: {"Users": user, "Concert": concert}.get(model.__name__)
        return db

    def test_success_returns_json_safe_dict_and_closes_session(self):
        concert_id, user_id = uuid.uuid4(), uuid.uuid4()
        user = MagicMock()
        db = self._db(user=user)
        result = MagicMock()
        result.model_dump.return_value = {"concert_id": str(concert_id)}

        with patch(f"{LOTTERY}.session", return_value=db), \
             patch(f"{LOTTERY}.LotteryDrawService.draw_lottery", return_value=result) as draw:
            out = draw_lottery_task(str(concert_id), str(user_id))

        assert out == {"concert_id": str(concert_id)}
        draw.assert_called_once_with(db, user, concert_id)
        result.model_dump.assert_called_once_with(mode="json")
        db.rollback.assert_not_called()
        db.close.assert_called_once()

    def test_failure_rolls_back_notifies_managers_and_reraises(self):
        concert = MagicMock()
        db = self._db(user=MagicMock(), concert=concert)

        with patch(f"{LOTTERY}.session", return_value=db), \
             patch(f"{LOTTERY}.LotteryDrawService.draw_lottery", side_effect=RuntimeError("boom")), \
             patch(f"{LOTTERY}.ConcertService.notify_managers_of_draw_failure") as notify:
            with pytest.raises(RuntimeError, match="boom"):
                draw_lottery_task(str(uuid.uuid4()), str(uuid.uuid4()))

        db.rollback.assert_called_once()
        notify.assert_called_once_with(db, concert)
        db.close.assert_called_once()

    def test_failure_for_missing_concert_skips_notification(self):
        db = self._db(user=MagicMock(), concert=None)

        with patch(f"{LOTTERY}.session", return_value=db), \
             patch(f"{LOTTERY}.LotteryDrawService.draw_lottery", side_effect=RuntimeError("boom")), \
             patch(f"{LOTTERY}.ConcertService.notify_managers_of_draw_failure") as notify:
            with pytest.raises(RuntimeError):
                draw_lottery_task(str(uuid.uuid4()), str(uuid.uuid4()))

        notify.assert_not_called()
        db.close.assert_called_once()
