# Architecture

How this codebase is put together and how to extend it consistently. This describes the
**actual current state of the code**, verified against the source — keep it that way as things
change. For *what the data model is* (tables, RBAC, business logic), see `database-design.md` in
this same folder. For *what's built vs. still open*, see `project_status.md`.

## 1. Tech stack

- **FastAPI** 0.122 (Python 3.12) + **Pydantic v2** (2.12.4) for request/response schemas.
- **PostgreSQL** via **SQLAlchemy 2.0** ORM (`app/db/models/*`), **Alembic 1.17** for migrations
  — one linear chain, no branches, one concern per migration.
- **Redis** for caching (`app/cache/cache_service.py`, msgpack-serialized, 5 min TTL on the
  product list) and rate limiting (`app/cache/rate_limit.py`, fixed-window counters — see
  `project_status.md`'s known-issues list for a real bug in this).
- **JWT** (python-jose, HS256): short-lived access tokens (`sub` = user id) + opaque UUID refresh
  tokens persisted in a `refresh_tokens` table, rotated on every login/refresh, delivered as an
  httponly/secure/samesite=lax cookie. A *separate* JWT secret (`JWT_EMAIL_SECRET_KEY`) signs
  email-verification and password-reset tokens, discriminated by a `type` claim (`verify` vs.
  `reset`), checked on decode so one can't be replayed as the other.
- **bcrypt** via passlib for password hashing.
- A `mock` payment gateway only (`PaymentGateway.mock`, driven by a `simulate_succ` flag) —
  real gateway integration (Razorpay or otherwise) is deferred to a later phase; `PaymentGateway`
  stays an enum with one member rather than being collapsed away, so a real gateway has somewhere
  to slot in later.
- **SendGrid** for transactional email, sent via FastAPI `BackgroundTasks`, never inline.
- **boto3** (optional — only imported when `STORAGE_BACKEND=s3`) for S3-compatible image storage;
  see §5.
- Docker Compose (`app` + `postgres:16` + `redis`) for local dev; the Dockerfile runs
  `alembic upgrade head` before `uvicorn`; `PYTHONDONTWRITEBYTECODE=1` is set to avoid a real
  stale-bytecode bug seen on Docker Desktop Windows bind mounts (coarse mtime resolution can fool
  Python's source-changed check) — see `project_status.md`.
- pytest + pytest-cov + **fakeredis** (`test/conftest.py` patches the real Redis client with a
  fake one for the whole test session) + GitHub Actions → Codecov → Render deploy hook.

## 2. Layered architecture — keep this shape for new domain code

Every feature follows the same three-layer split:

1. **`app/router/<feature>.py`** — FastAPI route functions only. Pulls `get_db`,
   `get_current_user`, `rate_limit(...)` as dependencies, calls exactly one service function, and
   translates the return value into an HTTP response/`HTTPException`. No ORM queries, no business
   logic here.
2. **`app/services/<feature>_service.py`** — business logic + ORM queries. Takes a `Session` as
   its first argument, never imports FastAPI. New domain logic (a lottery draw, seat allocation,
   scoping checks) belongs here, not in the router.
3. **`app/db/models/<feature>.py`** — SQLAlchemy models, all inheriting `Base`. `app/schema/
   <feature>.py` holds the paired Pydantic schemas (`*Create`, `*Read`/`*Out`/`*Response`,
   `*Update`) — request/response shapes are always separate classes from the ORM model, never the
   ORM model returned directly.

### Error-handling: two conventions coexist — match whichever the code you're touching uses

- **Sentinel returns** (most of the codebase, including all the idol/group/venue/concert/
  ticket-type/lottery services added this project): services return a plain value on success and
  either `False`/`None` (simple not-found/invalid) or a short string sentinel
  (`"forbidden"`/`"not_found"`/`"company_mismatch"`/`"conflict"`) for a mutating function that can
  fail more than one way. The router does `isinstance(result, str)` and maps each sentinel to its
  status code (403/404/400) — anything else (the ORM object, or `True` for a delete) is success.
  The exact sentinel vocabulary is **not** identical across every service file — read the service
  function before trusting what a given return value means; `product_service.py` in particular
  still uses plain `False` throughout rather than the string-sentinel convention.
- **Exceptions** (checkout/payment only): `app/exception/checkout.py` defines `CartItemError` and
  subclasses (`InsufficientStockError`, `AddressIdError`, `PaymentAmountMismatch`,
  `UnsupportedGatewayError`, `OrderError`, `PaymentError`, `PaymentFailedError`). Raised in the
  service, caught in the router (`order.py`, `payment.py`), mapped to a status code. Follow this
  pattern for new multi-step flows (a lottery draw, seat reservation) rather than threading
  sentinel values through several layers.
- **DB-trigger errors** (`app/exception/db_triggers.py`): a third, narrower variant of the
  exceptions pattern above, specifically for the 12 Postgres triggers/8 trigger functions listed
  in `database-design.md` §4/§4.1-4.2. `TriggerViolationError` + 8 named subclasses, a
  `translate_trigger_error()` that matches a caught `DBAPIError`'s Postgres message text against
  each trigger's known wording, and `commit_or_raise()`/`flush_or_raise()` drop-in replacements
  for a bare `db.commit()`/`db.flush()` at any write a trigger can fire on. Every subclass
  carries its own `status_code` (403 for the fan-only-purchase trigger, 400 for the rest), so a
  router's catch is one line: `except TriggerViolationError as e: raise HTTPException(e.status_code,
  str(e))`. Use this — not a bare `db.commit()` — for any new write that lands on a
  trigger-covered table; see `project_status.md` §4 item 9 for which service functions already
  use it and why (only the functions that actually reach a trigger-covered insert/update, not
  every function that touches that table).

## 3. Cross-cutting pieces, reused the same way from every router

- **`app/deps/auth.py::get_current_user`** — decodes the bearer JWT, loads the `Users` row, sets
  `request.state.user` (read by the rate limiter's `user_key`). `require_admin` and
  `require_manager_or_admin` (same file) check `current_user.role`
  (`admin`/`manager`/`fan`, `user_role_enum`), not the deprecated `is_admin` bool.
- **Company scoping** (multi-tenancy model): shared schema + a `company_id` column + service-layer
  filtering — **not** per-tenant Postgres schemas (that was drafted and explicitly rejected, see
  `database-design.md` §7.5's closing note). Every service that manages a company-owned resource
  (`groups`, `idols`, `concerts`, `ticket_types`, `lottery_campaigns`, `album_details`,
  `lightstick_details`) has a `_manager_scope_violation(current_user, company_id)`-shaped helper:
  `False` for an admin (always) or a manager whose own `company_id` matches the row being touched,
  `True` otherwise — returned as the `"forbidden"` sentinel above. Reads stay unscoped (public
  listings). `products` uses the same shape but resolves `company_id` indirectly — see
  `product_service._resolve_product_company_id()` — since a product has no `company_id` column of
  its own; ownership is derived from whichever of `album_details`/`lightstick_details` references
  it. `categories` intentionally has no scoping at all: every category-mutating endpoint is
  `require_admin`-only, so there's no per-company question to answer there.
- **`app/cache/rate_limit.py::rate_limit(limit, window, key_func)`** — a dependency factory used
  as `Depends(rate_limit(5, 60, ip_key))` / `..., user_key)`. Has a real bug (the key doesn't
  include the route, so endpoints sharing a `key_func` share one counter) — see
  `project_status.md` before reusing this as-is for anything scalper-sensitive (a ticket drop, a
  lottery-entry endpoint).
- **Image storage (`app/utils/storage.py`)** — an ABC (`StorageBackend`) with `LocalStorageBackend`
  and `S3StorageBackend` implementations, selected by `settings.STORAGE_BACKEND` via
  `get_storage()`. Every upload call site goes through `get_storage()` and never imports either
  backend directly, so local-dev vs. S3-for-deploy is a settings change, not a code change. Full
  detail in `database-design.md` §9.
- Domain exceptions (§2 above) caught centrally in the router that raises them.

## 4. Running locally

```bash
cp .env.example .env   # fill in real secrets
docker compose up --build
# API docs: http://localhost:8000/docs
```

New tables/columns always go through an Alembic migration (`alembic revision --autogenerate -m
"..."`, then review the generated file), never `Base.metadata.create_all()`. Enum types are
created with an atomic, idempotent `DO $$ BEGIN CREATE TYPE ... EXCEPTION WHEN duplicate_object
THEN NULL; END $$;` block (`op.execute(sa.text(...))`) rather than SQLAlchemy's
`Enum.create(bind, checkfirst=True)` — the latter is not crash-loop-safe if DB state and
Alembic's `alembic_version` table ever disagree. A `GENERATED ALWAYS AS ... STORED` column can't
cast to a Postgres user-defined enum (the enum's cast function is `STABLE`, not `IMMUTABLE`, and
Postgres rejects it) — use a plain `VARCHAR` generated column instead (see `venues.size`).

Tests: `pytest --cov=app` (needs a real Postgres; `fakeredis` handles Redis automatically via
`tests/conftest.py`, no real Redis needed locally) — split into `tests/unit/` (mocked, no DB) and
`tests/integration/` (real `TestClient` against the app). CI (`.github/workflows/test.yml`) spins up
Postgres 16 + Redis service containers, runs migrations, runs pytest with coverage, uploads to
Codecov, then deploys to Render on `main`/`master`.

## 5. Conventions to follow for new code

- Route prefixes/tags mirror the resource name, capitalized inconsistently in the original
  boilerplate (`/Cart`, `/Categories` vs. `/order`, `/payment`, `/products`) — match the casing of
  the *closest* existing sibling resource rather than introducing a third style.
- Every mutating/user-scoped query filters by `user_id` (fans) or `company_id` (managers) at the
  query level, not just via `get_current_user` — do the same for new tables.
- Pydantic schemas that wrap an ORM object always set `model_config = {"from_attributes": True}`.
- `with_for_update()` is the existing convention for locking a row before a mutating decision —
  keep the lock and the write in the *same* transaction/commit; don't let another `db.commit()`
  land in between (this is exactly the bug in `project_status.md`'s checkout item).
- **Every model file imports `Base` from `app.db.base_class`, never from `app.db.base`.**
  `app/db/base.py` is a pure aggregator — it imports every model module (for Alembic's
  `Base.metadata` to see them) and re-exports `Base` from `base_class`. Importing `Base` back
  from `app.db.base` in a model file reopens a real circular-import bug that was fixed this way
  (`app/deps/auth.py`/`app/router/products.py` import `app.db.models.user` directly, so whichever
  module Python touches first re-entering the other mid-import throws `ImportError`).
- New model modules must also be added to `app/db/base.py`'s import list, or standalone scripts
  (unlike the live app, whose routers transitively import everything) can hit
  `InvalidRequestError: ... failed to locate a name` when SQLAlchemy tries to resolve a
  string-based `relationship("ClassName", ...)` reference at mapper-configuration time.
- New tables that will feed the future ETL pipeline (`project_status.md`) should consider
  emitting a `domain_events` row in the same transaction as the write, even before the pipeline
  itself is built — cheap to add now, expensive to backfill later.
- No live Postgres/FastAPI/network access exists in the environments this has been built in so
  far — verification has relied on `py_compile` sweeps plus small AST-based static checks (every
  ORM `ForeignKey` target and `relationship(back_populates=...)` pair resolves and is reciprocal;
  every intra-app `from app.X import Y` resolves to a real name). Treat `alembic upgrade head` +
  hitting each endpoint against a real DB as the standing "still needs a real smoke test" item
  for anything built this way — noted per-feature in `project_status.md` rather than repeated
  here.
