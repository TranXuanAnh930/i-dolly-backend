# Architecture

How the codebase is organized and the conventions new code should follow. For the data model
(tables, RBAC, business logic), see `database-design.md`. For what's built vs. still open, see
`project_status.md`.

## 1. Tech stack

- **FastAPI** 0.122 (Python 3.12) + **Pydantic v2** (2.12.4) for request/response schemas.
- **PostgreSQL** via **SQLAlchemy 2.0** (`app/db/models/*`), **Alembic 1.17** for migrations — one
  linear chain, one concern per migration.
- **Redis** for caching (`app/cache/cache_service.py`, msgpack-serialized, 5-minute TTL) and rate
  limiting (`app/cache/rate_limit.py`, fixed-window counters).
- **Celery** (`app/celery_app.py`), broker + result backend on the same Redis instance but a
  separate DB index (`CELERY_BROKER_DB=1` vs `REDIS_DB=0`) so task keys never collide with
  cache/rate-limiter keys. Runs the lottery draw job and every transactional email send
  (`app/tasks/lottery.py`, `app/tasks/email.py`) today; new tasks go in `app/tasks/` and must be
  added to `celery_app.py`'s `include=[...]` list — a task not listed there is never discovered by
  a worker, even if it's `@celery_app.task`-decorated.
- **JWT** (python-jose, HS256): short-lived access tokens + opaque UUID refresh tokens in a
  `refresh_tokens` table, rotated on every login/refresh, delivered as an
  `httponly/secure/samesite=none` cookie. `samesite=none` because the frontend and API are on
  different origins — a `Lax` cookie wouldn't survive the cross-site refresh call. A separate
  secret (`JWT_EMAIL_SECRET_KEY`) signs email-verification/password-reset tokens, discriminated by
  a `type` claim so one can't be replayed as the other.
- **bcrypt** via passlib for password hashing.
- A `mock` payment gateway (`PaymentGateway.mock`, driven by `simulate_succ`) plus PayPal;
  `PaymentGateway` stays an enum so a future gateway has somewhere to slot in.
- **Resend** for transactional email, sent from the `app.tasks.email.send_email` Celery task —
  not `BackgroundTasks`, so a non-request-scoped caller (`lottery_draw_service.draw_lottery`, also
  a Celery task) can send mail too. Subject/body text for each email lives in
  `app/utils/email_templates.py`'s `EmailTemplate` enum, not inlined at the call site. With
  `settings.DEBUG=true`, email bodies (including verification/reset tokens) print to the console
  instead of sending, since `.env.example`'s `RESEND_API_KEY` is a placeholder — must stay
  `false` in production.
- **boto3** (only imported when `STORAGE_BACKEND=s3`) for S3-compatible image storage — see §3.
- Docker Compose (`app` + `postgres:16` + `redis`) for local dev; the Dockerfile runs
  `alembic upgrade head` before `uvicorn`. `PYTHONDONTWRITEBYTECODE=1` avoids a stale-bytecode
  issue on Docker Desktop Windows bind mounts.
- pytest + pytest-cov + fakeredis (`tests/conftest.py` swaps in a fake Redis client for the whole
  test session) + GitHub Actions → Codecov → Render deploy.

## 2. Layered architecture

Every feature follows the same three-layer split, inside one of four domain subpackages
(`identity/`, `talent/`, `events/`, `marketplace/`) plus a `shared/` subpackage for the one
genuinely cross-domain feature (notifications). `cart`/`order`/`payment`/`shipping` live under
`marketplace/`; `events`'s ticket checkout depending on `payment_service` crosses that boundary on
purpose.

1. **`app/router/<domain>/<feature>.py`** — route functions only. Pulls `get_db`,
   `get_current_user`, `rate_limit(...)` as dependencies, calls one service method, translates the
   result into an HTTP response or `HTTPException`. No ORM queries, no business logic.
2. **`app/services/<domain>/<feature>_service.py`** — every function for a feature as
   `@staticmethod`s on one class (`class TicketService: @staticmethod def checkout_ticket(db,
   ...): ...`), called as `TicketService.checkout_ticket(db, ...)`. The class is a namespace,
   never instantiated — `db` is passed per call. Private helpers are `@staticmethod`s on the same
   class, called via `ClassName._helper(...)`. Module-level constants stay outside the class.
   Business logic and ORM queries live here, never in the router.
3. **`app/db/models/<domain>/<feature>.py`** — SQLAlchemy models, all inheriting `Base`.
   `app/schema/<domain>/<feature>.py` holds the paired Pydantic schemas (`*Create`,
   `*Read`/`*Out`/`*Response`, `*Update`) — response shapes are always separate classes from the
   ORM model, never the ORM model returned directly.

   A generic ack response (`{"msg": "..."}`) uses `app/schema/common.py::MessageResponse` with
   `response_model=MessageResponse`. It lives outside every domain the same way
   `app/exception/common.py` does, since it's genuinely cross-domain. Page-shaped service
   functions (across `concert_service`, `idol_service`, `group_service`, `product_service`,
   `ticket_service`, `cart_service`, `order_service`, `cache_service`) construct and return the
   actual response schema instance rather than a bare `dict`. `product_service.
   _build_product_cards` returns `list[ProductCard]`, so callers read it by attribute
   (`card.artist`), not by dict key. `ProductWithCategoryRead` embeds the full `CategoryRead`
   object and is a separate schema from `ProductRead`, whose `category` field is a resolved name
   (`str`) built by `CacheService.get_cached_products`. `cache_service.py` follows the same
   one-class-of-`@staticmethod`s shape as item 2 above (`class CacheService: ...`, called as
   `CacheService.get_cached_products(db)`), not a flat module of functions — it imports the
   read-side services listed here for their query logic, which is also why invalidation calls live
   in the router right after the mutating service call, not inside the service itself (a service
   importing `cache_service` back would be circular).

Cross-service calls go through the class too (`PaymentService.create_ticket_payment(...)`, never a
bare function). Two same-named functions in different service files (e.g. both
`direct_sale_campaign_service.add_campaign` and `lottery_campaign_service.add_campaign`) are
unrelated and fine to coexist. `unittest.mock.patch()` on a cross-service call needs the
fully-qualified `"app.services.<domain>.<file>.<ClassName>.<method>"` path.

`app/db/base.py` aggregates every model via direct import so Alembic's `Base.metadata` sees them
all — keep its import list in sync by hand when a model file moves.

### Error handling: exceptions, not sentinels

Services raise `NotFoundError` (404), `ForbiddenError` (403), or `BadRequestError` (400) —
subclasses of `ServiceError` in `app/exception/common.py` — at the point a check fails, with a
message naming that specific failure. The router wraps the call once:

```python
try:
    return XService.method(...)
except ServiceError as e:
    raise HTTPException(status_code=e.status_code, detail=str(e)) from e
```

- A private helper whose result a caller needs to *inspect and override* before deciding it's an
  error (e.g. `idol_service._validate_refs`) stays sentinel-returning rather than raising directly.
- Plain reads returning `False`/`None` on "not found," handled inline in the router
  (`if not result: raise HTTPException(404, ...)`), are unaffected by this convention.
  - A bare list-returning read (`db.query(X).all()`, no further transformation) never checks its
    own result for emptiness — `return db.query(X).all()` directly, typed `-> list[X]:`, not
    `list[X] | None`. `.all()` already returns `[]`, never `None`, and `[]` is exactly as falsy as
    `None` to the router's `if not result:`, so re-wrapping it adds a branch that can never do
    anything different from just returning the list. The same collapse applies to a single-object
    read that's *only* `db.get(...)`/`.first()` immediately returned — `return db.get(X, id)`
    directly, still typed `X | None` since that call itself can genuinely return `None`. It does
    **not** apply once the query result gets wrapped into a bigger Pydantic object before
    returning (`EventsPageRead(concerts=...)`, `IdolDetailRead(idol=..., ...)`, `CartDetailRead(...)`)
    — a Pydantic model instance has no `__bool__`/`__len__`, so it's always truthy, and the
    `if not entity: return None` guard in front of it is the only way the router can still tell
    "nothing here" from "found." That guard stays.
- **Checkout/payment exceptions** (`app/exception/checkout.py`): `CartItemError` and subclasses
  (`InsufficientStockError`, `PaymentAmountMismatch`, `UnsupportedGatewayError`, etc.), raised in
  the service, caught in the router, mapped to a status code. Use this shape for new multi-step
  flows.
- **DB-trigger errors** (`app/exception/db_triggers.py`): `TriggerViolationError` + 8 named
  subclasses matching the 12 Postgres triggers in `database-design.md` §4. `commit_or_raise()` /
  `flush_or_raise()` replace a bare `db.commit()`/`db.flush()` at any write a trigger can fire on;
  each subclass carries its own `status_code`. A function can raise both a `TriggerViolationError`
  and a `ServiceError` (e.g. `ticket_service.checkout_ticket`) — the router catches both.

## 3. Cross-cutting pieces

- **`app/deps/auth.py::get_current_user`** — decodes the bearer JWT, loads the `Users` row, sets
  `request.state.user` (read by the rate limiter's `user_key`). `require_admin`/
  `require_manager_or_admin` check `current_user.role`, not the deprecated `is_admin` bool.
- **Company scoping**: shared schema + a `company_id` column + service-layer filtering, not
  per-tenant Postgres schemas. Every service managing a company-owned resource has a
  `_manager_scope_violation(current_user, company_id)` helper — `True` for a manager acting
  outside their own company, raised as `ForbiddenError`. Reads stay unscoped. `products` resolves
  `company_id` indirectly via `product_service._resolve_product_company_id()`, since a product has
  no `company_id` column of its own. `categories` has no scoping — every mutating endpoint is
  `require_admin`-only.
- **`app/cache/rate_limit.py::rate_limit(limit, window, key_func)`** — a dependency factory
  (`Depends(rate_limit(5, 60, ip_key))`). Keys fold in the route path (`_route_key`) so endpoints
  sharing a `key_func` don't share a counter. The limiter uses one atomic Redis `INCR` (creates the
  key at 1, else increments) with `EXPIRE` set only by the request that created the window — no
  check-then-act race. On a Redis error it logs and lets the request through (fail-open). Behind
  Render's reverse proxy, `main.py` wraps the app in
  `uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware` (`trusted_hosts="*"`, since only
  Render's own network can reach the container directly) so `request.client.host` is the real
  client IP before `ip_key` runs.

  **Coverage policy**:

  | Tier | Key | Typical limit | Why | Examples |
  |---|---|---|---|---|
  | Auth / brute-force | `ip_key` | 3–10 / 60s | Credential stuffing resistance | `register`, `login`, `forgot_password` |
  | Money / inventory | `user_key` | 3 / 60s | Reserves scarce inventory or money | `checkout_order`, `checkout_new_ticket`, `apply_to_lottery`, `add_to_cart` |
  | Privilege escalation | `user_key` | 3 / 60s | Grants elevated access | `make_admin`, `create_manager` |
  | Authenticated reads | `user_key` | 5–30 / 60s | Cheap, still worth a ceiling | `notifications/unread-count` (30), `me` (10) |
  | Public reads | `ip_key` | 5–10 / 60s | Anti-scraping / DB cost control | `products/all`, `products/search` |
  | Manager/admin CRUD | `user_key` | 20–30 / 60s | Safety net against a retry-loop, not a security control | most `talent`/`events`/`marketplace` admin routers |

- **Image storage (`app/utils/storage.py`)** — an ABC (`StorageBackend`) with
  `LocalStorageBackend`/`S3StorageBackend`, selected by `settings.STORAGE_BACKEND` via
  `get_storage()`. Every upload call site goes through `get_storage()`, never a backend directly.
- Domain exceptions (§2) are caught centrally in the router that raises them.

## 4. Running locally

```bash
cp .env.example .env   # fill in real secrets
docker compose up --build
# API docs: http://localhost:8000/docs
```

`docker compose up` also starts a `worker` service (`celery -A app.celery_app worker`). New
tables/columns always go through an Alembic migration, never `Base.metadata.create_all()`. Enum
types use an atomic idempotent `DO $$ BEGIN CREATE TYPE ... EXCEPTION WHEN duplicate_object THEN
NULL; END $$;` block rather than `Enum.create(bind, checkfirst=True)`, which isn't
crash-loop-safe. A `GENERATED ALWAYS AS ... STORED` column can't cast to a Postgres enum (the cast
function is `STABLE`, not `IMMUTABLE`) — use `VARCHAR` instead (see `venues.size`).

Tests: `pytest --cov=app`, split into `tests/unit/` (mocked, no DB) and `tests/integration/` (real
`TestClient`, needs Postgres). `tests/conftest.py` redirects `DATABASE_URL` onto a dedicated
`<name>_test` database before integration tests run, so they never touch dev data. CI spins up
Postgres 16 + Redis, runs migrations, runs pytest with coverage, uploads to Codecov, then deploys
to Render on `main`.

## 5. Conventions for new code

- Route prefixes/tags match the casing of the closest existing sibling resource — the original
  boilerplate mixed `/Cart`/`/Categories` with `/order`/`/payment`.
- Every mutating/user-scoped query filters by `user_id` or `company_id` at the query level, not
  just via `get_current_user`.
- Pydantic schemas wrapping an ORM object set `model_config = {"from_attributes": True}`.
- `with_for_update()` locks a row before a mutating decision; keep the lock and the write in the
  same transaction — don't let another `db.commit()` land in between.
- **Every model file imports `Base` from `app.db.base_class`, never `app.db.base`.**
  `app/db/base.py` is a pure aggregator that re-exports `Base` from `base_class`; importing it
  back from `app.db.base` in a model reopens a circular-import bug (`app/deps/auth.py` and
  `app/router/marketplace/products.py` both import `app.db.models.identity.user` directly).
- New model modules must be added to `app/db/base.py`'s import list, or standalone scripts can hit
  `InvalidRequestError: ... failed to locate a name` when SQLAlchemy resolves a string-based
  `relationship()` reference.
- New tables feeding the future ETL pipeline should emit a `domain_events` row in the same
  transaction as the write.
- No live Postgres/network access in the environments this is typically verified in —
  verification relies on `py_compile` sweeps and AST-based static checks (every
  `ForeignKey`/`relationship(back_populates=...)` pair resolves and is reciprocal; every intra-app
  import resolves). Treat `alembic upgrade head` plus hitting each endpoint against a real DB as
  the standing follow-up.
- **Every function needs a return type, every parameter needs a type** — enforced by ruff's `ANN`
  rules. `tests/*` and `scripts/*` are exempt.
  - The old sentinel-return convention (`Literal["forbidden", "not_found"]`) is superseded by the
    exception hierarchy in §2 wherever a router used `_raise_for`/`_raise_for_link` — those
    functions now return just the success type. A plain read's empty-result sentinel is `None`
    (`Object | None`), not `Literal[False]` — `None` is Python's actual "nothing here" value, and
    it's what `db.get(...)`/`.first()` already return on a miss, so a read that wraps one of those
    doesn't need to invent a second falsy value meaning the same thing. A private multi-value
    sentinel helper like `idol_service._validate_refs` still returns a sentinel rather than raising
    (see the bullet below this one) — but the sentinel itself is a local `class _RefIssue(str,
    Enum)` next to the helper, not a bare `Literal["a", "b", ...]`, for the same reason the next
    bullet gives for model columns: a typo in a member name is a `NameError`/`AttributeError` at
    the call site instead of a string that silently never matches any `if error == "...":` branch.
    `Literal` is still right for a genuinely one-off inline type hint, just not for a value set
    that gets compared against in more than one place.
  - **A fixed set of string values (role, status, sale method, tier, notification type, ...) is a
    `class X(str, Enum)` in the schema file that already owns the field's Read/Update model, never
    a bare `str` with the allowed values just noted in a comment.** The model's `Column` wires the
    same class in — `Column(Enum(OrderStatus, name="order_status_enum"))` — instead of a
    module-level `Enum("a", "b", "c", name=...)` with no Python-side type at all; `server_default=`
    stays the plain string label, since that's DDL text, not a Python default. This makes an
    invalid value a Pydantic validation error at the API boundary instead of a `CHECK`/enum
    violation surfacing as a raw `IntegrityError` deep in a commit. `role`/`TicketType.tier`/
    `TicketType.sale_method`/`Concert.status`/`LotteryCampaign.status`/`DirectSaleCampaign.status`/
    `LotteryEntry.status`/`Ticket.status`/`Notification.type`/`Notification.status`/
    `AlbumDetail.format` all follow this now. Doesn't apply to the exception-hierarchy sentinel
    strings from two bullets up (`Literal["forbidden", "not_found"]` and friends, now raised
    exceptions, not returned values) — those were never a model column's value set. A private
    multi-way sentinel *helper* like `_validate_refs` is a middle case: not a model column either,
    but compared against in more than one place, so it gets the enum treatment too (`_RefIssue`)
    rather than `Literal`, per the bullet just above.
  - **FastAPI gotcha**: a route's own return-type annotation becomes an implicit response schema
    when the decorator has no `response_model=`. A bare SQLAlchemy ORM class there crashes the app
    at import time. If a route has no `response_model=` and its real return type isn't
    Pydantic-serializable, set `response_model=None` explicitly.
