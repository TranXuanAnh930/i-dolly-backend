# Fix plan: a committed draw must never be reported as failed (bugs.md #25)

English | [日本語](lottery-draw-post-commit_JP.md)

**Status:** planned, not started (2026-09-27). Lottery code: to be hand-written; this doc is the
design only.

## Problem

`LotteryDrawService.draw_lottery` (`app/services/events/lottery_draw_service.py`) ends with:

```python
commit_or_raise(db)                                             # ① the draw is saved
CacheInvalidation.delete_cached_concert_detail(concert_id)      # ② Redis
ConcertService.notify_managers_of_draw_completion(db, concert)  # ③ inserts + a second commit
return LotteryResult(...)
```

`draw_lottery_task` (`app/tasks/lottery.py`) wraps the whole call in one `except Exception`, which
rolls back, sends `lottery_draw_failed` to the company's managers and re-raises. It can't tell a
failure **before** ① (the draw really failed, nothing was saved) from one **after** ① (the draw is
saved; only a side effect failed).

Triggers after ①:
- ② raises `redis.ConnectionError` while Redis is down (#11).
- ③'s commit fails (dropped connection, trigger error).

Result when that happens:
- Winners have `pending_payment` tickets, seats are reserved, campaigns are `drawn`, and fans already
  got `lottery_result` notifications (those were in commit ①) — but managers are told the draw
  **failed**.
- Celery records the task as `FAILURE`.
- A manager who re-triggers gets "No open lottery campaigns" (the campaigns are `drawn`) — the data
  is safe, but the message makes it look worse.
- If ③ failed because the connection dropped, `notify_managers_of_draw_failure`'s own commit fails
  too, and that exception replaces the original one in the logs.

## Decision

**The commit is the boundary.** An error before commit ① is a draw failure; anything after it is a
best-effort side effect that is logged and never reaches the failure path.

Chosen shape — **move the post-commit steps out of the service into the task** (option B):

- `draw_lottery` ends at `commit_or_raise(db)` and returns `LotteryResult`. It no longer invalidates
  the cache or notifies managers of completion.
- `draw_lottery_task` runs the draw inside the existing `try/except` (failure path unchanged), then
  runs the post-commit steps **outside** it, each in its own guard.

Rejected alternative (option A): keep ② and ③ in the service, each in its own `try/except`. Smaller
diff, but the "committed = succeeded" rule then depends on every future post-commit line remembering
its own try/except. With B, the task's structure enforces it: nothing after the draw call can reach
the failure branch.

Not in scope: retrying the completion notification. If ③ fails the managers get no completion
notice; the draw result is still visible on the results page
(`GET /lottery_entries/concert/{concert_id}/results`). Logged, accepted.

## Target shape (sketch, not final code)

```python
@celery_app.task(name="app.tasks.lottery.draw_lottery")
def draw_lottery_task(concert_id: str, user_id: str) -> dict:
    db = session()
    try:
        try:
            current_user = db.get(Users, uuid.UUID(user_id))
            result = LotteryDrawService.draw_lottery(db, current_user, uuid.UUID(concert_id))
        except Exception:
            # Nothing was committed: report the failure.
            db.rollback()
            ...notify_managers_of_draw_failure (guarded, see step 3)...
            raise

        # The draw is committed. Side effects below are best-effort.
        _after_draw(db, uuid.UUID(concert_id))
        return result.model_dump(mode="json")
    finally:
        db.close()


def _after_draw(db, concert_id) -> None:
    try:
        CacheInvalidation.delete_cached_concert_detail(concert_id)
    except Exception:
        logger.exception("draw %s: cache invalidation failed", concert_id)
    try:
        concert = db.get(Concert, concert_id)
        ConcertService.notify_managers_of_draw_completion(db, concert)
    except Exception:
        db.rollback()
        logger.exception("draw %s: completion notification failed", concert_id)
```

## Steps

1. **Service**: remove ② and ③ from `draw_lottery`; it returns right after `commit_or_raise(db)`.
   Drop the now-unused `CacheInvalidation`/`ConcertService` imports if nothing else uses them.
2. **Task**: split `draw_lottery_task` as above — draw inside the failure `try`, post-commit steps
   in `_after_draw`, each guarded separately (a Redis failure mustn't skip the notification).
3. **Guard the failure notification too**: wrap `notify_managers_of_draw_failure` in its own
   `try/except` that logs, so a failure there can't replace the original exception; then `raise`
   the original.
4. **Logging**: `logging.getLogger(__name__)` in `app/tasks/lottery.py` (shared with the #11 plan's
   first use of `logging`).
5. **Callers that call the service directly**: `tests/integration/events/test_lottery_concurrency.py`
   calls `draw_lottery` without the task. After step 1 those tests no longer produce the completion
   notification or cache delete. None of the integration tests assert on either (checked
   2026-09-27). `scripts/seed.py` doesn't call it.
6. **Tests** (`tests/unit/tasks/test_lottery_task.py`, new; patch `session`, the service and
   `ConcertService`):
   - completion notification raises → task returns the result, `notify_managers_of_draw_failure`
     not called, no re-raise.
   - cache invalidation raises → completion notification still sent, task returns the result.
   - draw raises → rollback, failure notification sent, original exception re-raised.
   - draw raises **and** the failure notification raises → the **original** exception propagates.
   - Update `tests/unit/events/test_lottery_draw_service.py` (it asserts
     `notify_managers_of_draw_completion` is called from the service, line ~143) → assert it
     isn't; the task tests now own that behaviour.
   - Negative control: the first two tests fail against the current code.
7. **Docs**: tick #25 in `bugs.md`; `project_status.md` §8 (draw job) — the completion notice is
   now sent by the task after the commit, best-effort; `docs/database-design.md` lottery sequence
   diagram if it shows the completion notification inside the draw's transaction.

## Related

- **#11** (`docs/plans/redis-outage.md`) makes ② stop raising on its own. This fix is still needed:
  ③ can fail independently, and the boundary should hold for any future post-commit step.
- **#24** (draw complexity) and **#6** (dedupe by user) touch the same service; independent of this.
