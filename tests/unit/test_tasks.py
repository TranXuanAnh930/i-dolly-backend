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

    # --- bugs.md #25: anything after the draw's commit must never reach the failure path.

    def _succeeding_draw(self):
        result = MagicMock()
        result.model_dump.return_value = {"ok": True}
        return patch(f"{LOTTERY}.LotteryDrawService.draw_lottery", return_value=result)

    def test_failing_completion_notification_does_not_fail_the_draw(self):
        db = self._db(user=MagicMock(), concert=MagicMock())

        with patch(f"{LOTTERY}.session", return_value=db), self._succeeding_draw(), \
             patch(f"{LOTTERY}.ConcertService.notify_managers_of_draw_completion", side_effect=RuntimeError("db gone")), \
             patch(f"{LOTTERY}.ConcertService.notify_managers_of_draw_failure") as notify_failure:
            out = draw_lottery_task(str(uuid.uuid4()), str(uuid.uuid4()))

        assert out == {"ok": True}
        notify_failure.assert_not_called()
        db.rollback.assert_not_called()
        db.close.assert_called_once()

    def test_failing_cache_clear_still_sends_the_completion_notification(self):
        concert = MagicMock()
        db = self._db(user=MagicMock(), concert=concert)

        with patch(f"{LOTTERY}.session", return_value=db), self._succeeding_draw(), \
             patch(f"{LOTTERY}.CacheInvalidation.delete_cached_concert_detail", side_effect=RuntimeError("redis")), \
             patch(f"{LOTTERY}.ConcertService.notify_managers_of_draw_completion") as notify_completion, \
             patch(f"{LOTTERY}.ConcertService.notify_managers_of_draw_failure") as notify_failure:
            out = draw_lottery_task(str(uuid.uuid4()), str(uuid.uuid4()))

        assert out == {"ok": True}
        notify_completion.assert_called_once_with(db, concert)
        notify_failure.assert_not_called()

    def test_post_commit_steps_run_after_the_draw_for_that_concert(self):
        concert_id = uuid.uuid4()
        concert = MagicMock()
        db = self._db(user=MagicMock(), concert=concert)
        order = MagicMock()

        with patch(f"{LOTTERY}.session", return_value=db), \
             patch(f"{LOTTERY}.LotteryDrawService.draw_lottery", side_effect=order.draw), \
             patch(f"{LOTTERY}.CacheInvalidation.delete_cached_concert_detail", side_effect=order.invalidate), \
             patch(f"{LOTTERY}.ConcertService.notify_managers_of_draw_completion", side_effect=order.notify):
            draw_lottery_task(str(concert_id), str(uuid.uuid4()))

        assert [c[0] for c in order.mock_calls[:3]] == ["draw", "invalidate", "notify"]
        order.invalidate.assert_called_once_with(concert_id)

    def test_a_failed_draw_runs_no_post_commit_steps(self):
        db = self._db(user=MagicMock(), concert=MagicMock())

        with patch(f"{LOTTERY}.session", return_value=db), \
             patch(f"{LOTTERY}.LotteryDrawService.draw_lottery", side_effect=RuntimeError("boom")), \
             patch(f"{LOTTERY}.CacheInvalidation.delete_cached_concert_detail") as invalidate, \
             patch(f"{LOTTERY}.ConcertService.notify_managers_of_draw_completion") as notify_completion, \
             patch(f"{LOTTERY}.ConcertService.notify_managers_of_draw_failure"):
            with pytest.raises(RuntimeError, match="boom"):
                draw_lottery_task(str(uuid.uuid4()), str(uuid.uuid4()))

        invalidate.assert_not_called()
        notify_completion.assert_not_called()

    def test_failing_failure_notification_does_not_mask_the_draw_error(self):
        db = self._db(user=MagicMock(), concert=MagicMock())

        with patch(f"{LOTTERY}.session", return_value=db), \
             patch(f"{LOTTERY}.LotteryDrawService.draw_lottery", side_effect=RuntimeError("boom")), \
             patch(f"{LOTTERY}.ConcertService.notify_managers_of_draw_failure", side_effect=ValueError("db gone")):
            with pytest.raises(RuntimeError, match="boom"):
                draw_lottery_task(str(uuid.uuid4()), str(uuid.uuid4()))

        db.close.assert_called_once()

    def test_failing_concert_lookup_does_not_mask_the_draw_error(self):
        db = MagicMock()
        db.get.side_effect = lambda model, _id: MagicMock() if model.__name__ == "Users" else (_ for _ in ()).throw(RuntimeError("db gone"))

        with patch(f"{LOTTERY}.session", return_value=db), \
             patch(f"{LOTTERY}.LotteryDrawService.draw_lottery", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                draw_lottery_task(str(uuid.uuid4()), str(uuid.uuid4()))

    def test_malformed_concert_id_opens_no_session(self):
        with patch(f"{LOTTERY}.session") as open_session:
            with pytest.raises(ValueError):
                draw_lottery_task("not-a-uuid", str(uuid.uuid4()))

        open_session.assert_not_called()
