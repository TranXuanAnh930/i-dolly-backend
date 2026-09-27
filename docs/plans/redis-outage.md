# Fix plan: survive a Redis outage (bugs.md #11)

**Status:** planned, not started (2026-09-27).

## Problem

Redis serves three roles. Only one of them handles an outage:

| Role | Code | On `RedisError` |
|---|---|---|
| Rate limiting | `app/cache/rate_limit.py` | Caught, request allowed (fail-open) |
| Cached reads | `CacheService.get_cached_*` (`app/cache/cache_service.py`) | Uncaught → 500 |
| Invalidation after writes | `CacheInvalidation.delete_*` (`app/cache/invalidation.py`) | Uncaught → 500, **after the DB commit** |
| Celery broker (email, draw) | `celery_app.send_task(...)` in routers/services | Uncaught → 500, also after the commit |

1. **Reads fail although Postgres could answer.** `redis_client.get()` raises before the DB
   fallback runs, so the store, events, detail and manager pages all 500. A cache outage becomes a
   site outage.
2. **Successful writes are reported as failures.** e.g. `OrderService.checkout`:
   `commit_or_raise(db)` saves the order, payment and stock change, then
   `CacheInvalidation.delete_cached_products()` raises. The fan gets a 500 for a paid order, no
   confirmation email (the router's `send_task` never runs), and may re-checkout with a new
   idempotency key → duplicate order. Same shape in payment finalization, ticket checkout, the
   lottery draw (#25) and every manager create/update/delete.
3. **Hangs instead of failures.** `app/cache/redis_client.py` sets no `socket_timeout` /
   `socket_connect_timeout`. A refused connection fails fast, but a silently dropped one blocks until
   the OS gives up. Each stuck request holds a threadpool thread and a DB connection (pool 5 + 5), so
   a handful can stall the whole API.

## Decisions

- **Reads fail open**: on `RedisError`, build the response from Postgres and skip the cache write.
- **Failed invalidation is logged and swallowed.** The commit can't be undone, so the response must
  reflect it. Cost: a stale cache entry after Redis recovers, bounded by `TTL_SECONDS` (5 min).
  Accepted for a portfolio project; noted in `architecture.md`. (If Redis restarts empty, which
  Render Key Value does with `persistenceMode: off`, there's nothing stale at all.)
- **Short client timeouts**: `socket_connect_timeout=1`, `socket_timeout=1` (seconds). Redis calls
  normally take < 5 ms; 1 s is far above normal and still frees threads quickly.
- **Post-commit `send_task` is best-effort**: log and continue. The email is lost, which matches the
  existing "email failures are swallowed" smell; a real fix is an outbox (see the OLAP future work).
  Does **not** apply to `PUT /concerts/lottery-draw/{id}`, where enqueueing *is* the operation — that
  one should still fail loudly (503) so the manager can retry.
- One guard in the cache layer, not try/except in each router.

## Steps

1. **Timeouts** in `app/cache/redis_client.py`: add `socket_connect_timeout` and `socket_timeout`
   (settings `REDIS_SOCKET_TIMEOUT: float = 1.0`). Consider `health_check_interval=30`.
2. **Invalidation guard** in `app/cache/invalidation.py`: a small decorator (or context manager),
   e.g. `@_best_effort`, that catches `redis.RedisError`, logs `"cache invalidation skipped: ..."`
   with the method name, and returns `None`. Apply to every `delete_*` and `_delete_matching`.
3. **Read guard** in `app/cache/cache_service.py`: wrap the `get` and the `setex` of each
   `get_cached_*`. A failed `get` → treat as a miss; a failed `setex` → return the payload anyway.
   Simplest shape: two helpers, `_cache_get(key) -> bytes | None` and `_cache_set(key, value)`, each
   swallowing `RedisError`, and every `get_cached_*` calls those instead of `redis_client` directly.
4. **Post-commit email dispatch**: a helper (e.g. `app/utils/email_dispatch.py::dispatch_email`) that
   wraps `celery_app.send_task("app.tasks.email.send_email", ...)` in `try/except
   kombu.exceptions.OperationalError` (+ `redis.RedisError`), logs, and continues. Replace the direct
   `send_task` calls for emails. Keep the lottery-draw enqueue as-is but map its failure to 503.
   Check the publish retry policy too: Celery retries a publish by default, which can add seconds of
   delay — set `broker_transport_options`/`task_publish_retry_policy` so it gives up quickly.
5. **Logging**: use `logging.getLogger(__name__)`, not `print` (first real use of `logging` in
   `app/`; the rate limiter's `print` can move over at the same time).
6. **Tests**
   - Unit: patch `redis_client.get`/`setex`/`delete` to raise `redis.ConnectionError`; assert each
     `get_cached_*` returns DB data and each `delete_*` returns without raising.
   - Unit: `OrderService.checkout` with invalidation raising → returns the order (no exception).
   - Unit: `dispatch_email` with `send_task` raising → no exception.
   - Integration (optional): point a second client at an unused port and hit a cached page +
     checkout; expect 200 and correct data.
   - Negative control: each test fails against the current code.
7. **Docs**: `architecture.md` (cache section: fail-open reads, best-effort invalidation, timeouts,
   staleness bound), `project_status.md` §4, tick #11 in `bugs.md`.

## Related

- **#25** (draw reported as failed): Redis being down is one trigger — the post-commit
  `delete_cached_concert_detail` raises inside the draw. Step 2 removes that trigger, but #25 has
  its own fix (separate post-commit steps from the draw's failure path).
- **#22**'s other half and **#7** also touch `rate_limit.py`; no conflict with this plan.
