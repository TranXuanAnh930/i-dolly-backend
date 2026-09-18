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
- **Celery** (`app/celery_app.py`), broker + result backend on the same Redis instance but
  `CELERY_BROKER_DB` (default `1`) instead of `REDIS_DB` (default `0`), so task/result keys never
  collide with the cache or rate-limiter keyspace. Currently a bare skeleton — one placeholder
  task (`app/tasks/example.py`'s `ping`) proves the worker/broker/backend wiring, nothing else
  runs through it yet. See `project_status.md` §5 for which background jobs (the lottery draw,
  async email, the ETL pipeline) are still undecided/unbuilt on top of this.
- **JWT** (python-jose, HS256): short-lived access tokens (`sub` = user id) + opaque UUID refresh
  tokens persisted in a `refresh_tokens` table, rotated on every login/refresh, delivered as an
  httponly/secure/samesite=none cookie — samesite=none (not lax) because the frontend and this API
  are deployed on different origins (e.g. Vercel + Render); a Lax cookie is never sent on the
  cross-site XHR/fetch POST /account/refresh call the frontend makes after a page reload, only on
  top-level navigations, so refresh always failed there and every reload logged fans out. A
  *separate* JWT secret (`JWT_EMAIL_SECRET_KEY`) signs
  email-verification and password-reset tokens, discriminated by a `type` claim (`verify` vs.
  `reset`), checked on decode so one can't be replayed as the other.
- **bcrypt** via passlib for password hashing.
- A `mock` payment gateway only (`PaymentGateway.mock`, driven by a `simulate_succ` flag) —
  real gateway integration (Paypal or otherwise) is deferred to a later phase; `PaymentGateway`
  stays an enum with one member rather than being collapsed away, so a real gateway has somewhere
  to slot in later.
- **SendGrid** for transactional email, sent via FastAPI `BackgroundTasks`, never inline.
  `settings.DEBUG` (default `false`) is a dev-only escape hatch, not a real email provider switch:
  `app/utils/email_sender.py`'s `send_email` prints the full body — including whatever
  verification/reset token it carries — to the console before attempting the real SendGrid call,
  and swallows that call's failure instead of raising inside the background task. Needed because
  `.env.example`'s `SENDGRID_API_KEY` is a placeholder, so local dev never actually delivers mail;
  without this the token had nowhere visible to land. Must stay `false` in production — these
  bodies carry live auth tokens.
- **boto3** (optional — only imported when `STORAGE_BACKEND=s3`) for S3-compatible image storage;
  see §5.
- Docker Compose (`app` + `postgres:16` + `redis`) for local dev; the Dockerfile runs
  `alembic upgrade head` before `uvicorn`; `PYTHONDONTWRITEBYTECODE=1` is set to avoid a real
  stale-bytecode bug seen on Docker Desktop Windows bind mounts (coarse mtime resolution can fool
  Python's source-changed check) — see `project_status.md`.
- pytest + pytest-cov + **fakeredis** (`test/conftest.py` patches the real Redis client with a
  fake one for the whole test session) + GitHub Actions → Codecov → Render deploy hook.

## 2. Layered architecture — keep this shape for new domain code

Every feature follows the same three-layer split. Each layer's directory is further split into
the four domain subpackages from CLAUDE.md §4 (`identity/`, `talent/`, `events/`, `marketplace/`),
plus a `shared/` subpackage for the one genuinely cross-domain feature (notifications — used by
all four, owned by none). `cart`/`order`/`payment`/`shipping` live under `marketplace/` per
CLAUDE.md §4's own framing ("Marketplace... reusing the original cart/order/payment/shipping
machinery"), even though `events/`'s ticket checkout also depends on `payment_service` — that's an
accepted cross-domain import, not a sign the file is misplaced. New domain code goes in whichever
of the five subpackages its concept belongs to; if it's genuinely used by all four (like
notifications), it goes in `shared/`, not force-fit into one:

1. **`app/router/<domain>/<feature>.py`** — FastAPI route functions only. Pulls `get_db`,
   `get_current_user`, `rate_limit(...)` as dependencies, calls exactly one service method, and
   translates the return value into an HTTP response/`HTTPException`. No ORM queries, no business
   logic here.
2. **`app/services/<domain>/<feature>_service.py`** — every function for one feature grouped into
   a single class of `@staticmethod`s, e.g. `class TicketService: @staticmethod def
   checkout_ticket(db: Session, ...): ...`, called as `TicketService.checkout_ticket(db, ...)` —
   the class is a pure namespace, not an instance: `db: Session` is still passed into each call
   like before, nothing is bound at construction (there is no `__init__`, and these are never
   instantiated). Private helpers (`_manager_scope_violation` and friends) are `@staticmethod`s on
   the same class too — call them via `ClassName._helper(...)`, a bare `_helper(...)` no longer
   resolves once it's a method. Module-level constants a file's methods reference (e.g.
   `_LIVE_STATUSES`) stay outside the class, sitting above it — moving them in would need
   `ClassName._LIVE_STATUSES` everywhere for no benefit, since a bare name inside a method already
   resolves fine via the module's globals regardless of whether the method is classed. Business
   logic + ORM queries live here, never FastAPI. New domain logic (a lottery draw, seat allocation,
   scoping checks) belongs here, not in the router.
3. **`app/db/models/<domain>/<feature>.py`** — SQLAlchemy models, all inheriting `Base`.
   `app/schema/<domain>/<feature>.py` holds the paired Pydantic schemas (`*Create`,
   `*Read`/`*Out`/`*Response`, `*Update`) — request/response shapes are always separate classes
   from the ORM model, never the ORM model returned directly.

Cross-service calls go through the class too (`PaymentService.create_ticket_payment(...)`, not a
bare `create_ticket_payment(...)`) — every router and every service-to-service reference imports
the class, not individual function names. The two exceptions worth knowing about: two service
files can legitimately define a same-named private helper or public function independently (e.g.
`direct_sale_campaign_service.add_campaign` and `lottery_campaign_service.add_campaign` are
unrelated functions that happen to share a name) — this is harmless as long as no single call site
ever needs both at once, so nothing was renamed to avoid it. And `unittest.mock.patch()` calls in
`tests/unit/test_services.py` that target a cross-service function by its old dotted path (e.g.
patching `_build_product_cards`, called by `group_service` but defined on `ProductService`) now
need the fully-qualified `"app.services.<domain>.<file>.<ClassName>.<method>"` string instead —
`mock.patch` supports patching a class attribute this way, same as patching a module-level name.

`app/db/base.py` still aggregates every model with a direct import (not moved — it isn't a
feature of any one domain), so its own import lines are the one place that must stay in sync by
hand whenever a model file moves or a new one is added; see its own CORRECTION comment for why
this matters more than it looks (SQLAlchemy's string-based `relationship()` resolution).

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
  `merch_details`) has a `_manager_scope_violation(current_user, company_id)`-shaped helper:
  `False` for an admin (always) or a manager whose own `company_id` matches the row being touched,
  `True` otherwise — returned as the `"forbidden"` sentinel above. Reads stay unscoped (public
  listings). `products` uses the same shape but resolves `company_id` indirectly — see
  `product_service._resolve_product_company_id()` — since a product has no `company_id` column of
  its own; ownership is derived from whichever of `album_details`/`merch_details` references
  it. `categories` intentionally has no scoping at all: every category-mutating endpoint is
  `require_admin`-only, so there's no per-company question to answer there.
- **`app/cache/rate_limit.py::rate_limit(limit, window, key_func)`** — a dependency factory used
  as `Depends(rate_limit(5, 60, ip_key))` / `..., user_key)`. This entry was stale: it used to warn
  that the key didn't include the route (so endpoints sharing a `key_func` shared one counter) —
  that was fixed early in this file's own history (`_route_key` folds in
  `request.scope["route"].path`) and this doc never caught up; corrected here. Two other real bugs
  were found and fixed since (a non-atomic check-then-act race, and no fail-open on a Redis error) —
  see `project_status.md` §4 item 2 for the fix and the regression tests
  (`tests/unit/test_rate_limit.py`) that caught two follow-on bugs in the first attempt at that fix.
  **Still open**: `ip_key` trusts `request.client.host` directly, so behind Render's reverse proxy
  every visitor likely shares one IP-bucket — `project_status.md` §4 item 2 has the concrete plan
  (`uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware`, not a hand-rolled `X-Forwarded-For`
  parse, which would be spoofable).

  **Coverage policy** — which tier a route belongs to decides whether/how it's rate-limited; a new
  route should be checked against this table, not left to individual judgement:

  | Tier | Key | Typical limit | Why | Examples |
  |---|---|---|---|---|
  | Auth / brute-force | `ip_key` | 3–10 / 60s | Credential stuffing resistance | `register`, `login`, `forgot_password` |
  | Money / inventory | `user_key` | 3 / 60s | Reserves scarce inventory or money — includes lottery entry, not just checkout | `checkout_order`, `checkout_new_ticket`, `apply_to_lottery`, `add_to_cart` |
  | Privilege escalation | `user_key` | 3 / 60s | Grants elevated access | `make_admin`, `create_manager` |
  | Authenticated reads | `user_key` | 5–30 / 60s, scaled to how pollable the endpoint is | Cheap and safe, but still worth a ceiling | `notifications/unread-count` (30, polled), `me` (10) |
  | Public reads | `ip_key` | 5–10 / 60s | Anti-scraping / DB cost control on an unauthenticated GET | `products/all`, `products/search` |
  | Manager/admin CRUD | `user_key` | 20–30 / 60s | Already gated by auth + company-scoping — this tier is a safety net against a buggy client retry-loop, not a security control | most `talent`/`events`/`marketplace` admin routers |

  Found via this table, not guesswork: `lottery_entries/apply` and `cart/add_cart` were both
  completely unrated-limited despite being money/inventory-tier — fixed. `direct_sale_campaign`,
  `lottery_campaign`, `lottery_preference`, `ticket_type`, `album_detail`, `genre`, `merch_detail`
  routers had zero coverage at all — now on the manager/admin-CRUD tier.
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

`docker compose up` also starts a `worker` service (same image, `celery -A app.celery_app worker`)
alongside `app`/`postgres`/`redis` — see §1's Celery entry. New tasks go in `app/tasks/`, added to
`app/celery_app.py`'s `include=[...]` list so the worker picks them up (no autodiscovery is
configured).

New tables/columns always go through an Alembic migration (`alembic revision --autogenerate -m
"..."`, then review the generated file), never `Base.metadata.create_all()`. Enum types are
created with an atomic, idempotent `DO $$ BEGIN CREATE TYPE ... EXCEPTION WHEN duplicate_object
THEN NULL; END $$;` block (`op.execute(sa.text(...))`) rather than SQLAlchemy's
`Enum.create(bind, checkfirst=True)` — the latter is not crash-loop-safe if DB state and
Alembic's `alembic_version` table ever disagree. A `GENERATED ALWAYS AS ... STORED` column can't
cast to a Postgres user-defined enum (the enum's cast function is `STABLE`, not `IMMUTABLE`, and
Postgres rejects it) — use a plain `VARCHAR` generated column instead (see `venues.size`).

Tests: `pytest --cov=app` (needs a real Postgres only for `tests/integration/`; `fakeredis` handles
Redis automatically via `tests/conftest.py`, no real Redis needed locally) — split into
`tests/unit/` (mocked, no DB) and `tests/integration/` (real `TestClient` against the app). CI
(`.github/workflows/test.yml`) spins up Postgres 16 + Redis service containers, runs migrations,
runs pytest with coverage, uploads to Codecov, then deploys to Render on `main`/`master`.

**Integration tests never touch whatever database `DATABASE_URL` points at.**
`tests/conftest.py` redirects it onto a dedicated `<name>_test` database (a same-instance sibling,
not the same one the running `app`/`worker` — or your own manual frontend testing, or
`scripts/seed.py` — use) before anything else in the process can read the original value; then
`tests/integration/conftest.py` drops, recreates, and fully migrates that database once per test
session, before any integration test module is imported. `pytest tests/unit` is unaffected (the
redirect is a pure string rewrite, no connection attempted) and still needs no live Postgres.
Practical effect: `pytest tests` is safe to run against any local dev setup, any time, with a
deterministic result — it can't see or corrupt real seeded/manually-created rows, and doesn't
require you to keep a scratch database empty by hand. (CI's own standalone "run alembic upgrade
head" step against its service-container Postgres still runs and still has to pass, but pytest no
longer actually queries the database that step migrated — it creates and migrates its own
`<ci-db>_test` sibling instead; harmless, just means that CI step is now an independent
migration-chain smoke check rather than a precondition pytest depends on.)

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
  (`app/deps/auth.py`/`app/router/marketplace/products.py` import `app.db.models.identity.user`
  directly, so whichever module Python touches first re-entering the other mid-import throws
  `ImportError`).
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
