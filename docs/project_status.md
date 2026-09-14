# Project Status

A snapshot of what's built, what's verified, and what's still open — read this before assuming
something exists or is finished. `database-design.md` (same folder) is the schema/business-logic
design; `architecture.md` is how the code is organized; this file is the "where are we right
now" layer, and the one most likely to go stale — update it whenever a feature actually lands or
a known issue gets fixed, don't let it drift into aspirational state.

## 1. Current migration state

43 migrations, one linear chain, no branches. Chain head: **`133d9b4f9d17`**
(`rename_leftover_lightstick_details_constraint_names`, chained onto `b60aec9ffc02`) — **generated,
reviewed, not yet applied anywhere.** `b60aec9ffc02` (`merge_lightstick_category_into_merch`) itself
**is applied** to the local Docker Compose Postgres (confirmed via `alembic current`) — the
application-code side of the rename (models/schema/service/router, `product_service.py`'s
resolvers, `scripts/seed.py`) also landed, done by hand rather than by Claude (migration/DDL work
was Claude's — catalog renames and trigger-function bodies are "get the mechanics right," not a
novel design judgment call). Both verified live: `py_compile` + a real `configure_mappers()`/
`import main` check (146 routes, exactly 5 `/merch_details/*`, zero `lightstick` routes) +
`pytest tests/unit` (56/61, same 5 pre-existing item-11 failures, no regressions).

**`133d9b4f9d17` exists because `b60aec9ffc02` was incomplete** — querying the live local DB
directly (`pg_constraint`/`pg_indexes`, not re-reading the migration source) after applying it
found 5 leftover `lightstick_details_*`-named objects: the primary key constraint and all 4 foreign
key constraints (`product_id`/`idol_id`/`group_id`/`color_id`). `b60aec9ffc02` only renamed the
objects it had given an explicit name to (`chk_lightstick_details_owner`, the 3 `ix_lightstick_
details_*` indexes) — `ALTER TABLE ... RENAME TO` doesn't rename constraints at all, named or
Postgres-auto-named alike, and the PK/FK constraints here were never given explicit names in the
original `a9e33e281ffe` migration, so they were never on the list of things to rename in the first
place. Real gap, found by checking the live database rather than trusting the migration file was
complete — see `database-design.md` §3.17 for the fuller writeup. **Not yet applied anywhere.**

Previous head, what the live local DB is actually running: **`b60aec9ffc02`**. Before that:
`df79d71c6a2c` (`create_notifications_table`, chained onto `10f9dfa05636`). Before that:
`10f9dfa05636` (`extend_idol_colors_and_genres` — adds 17 more `idol_colors` rows and 5 more
`genres` rows needed for the expanded seed roster below; previous head was `019b674bf0c1`,
`add_image_url_to_products`). All 18 domain tables from `database-design.md` §1–§3 plus the
pre-existing e-commerce tables are migrated. `schema.sql`, referenced throughout
`database-design.md` as "the reference DDL," **does not exist as a file in this repo** — every
migration was written directly against the design doc's table-by-table notes, not transcribed
from a DDL file. If a `schema.sql` is wanted (e.g. for an ERD tool, or a single-file review
artifact), it would need to be generated from the live migrations/models, not assumed present.

**Every primary/foreign key is now a UUID, not a sequential integer** (enumeration resistance —
see `database-design.md`'s intro for the rationale). Since none of these 40 migrations has ever
run against a real Postgres instance (§3 below), they were edited **in place** rather than
layering `ALTER COLUMN` migrations on top — revision ids and the `down_revision` chain are
unchanged, only column type definitions changed. This touched every model, every migration,
every Pydantic schema, every router/service id parameter, the JWT `sub` claim handling
(`app/utils/jwt_manager.py`, `app/deps/auth.py` — decode to `uuid.UUID` instead of `int`), and
the product-list Redis cache (`app/cache/cache_service.py` now stringifies `p.id` before
`msgpack.packb`, since msgpack has no native UUID type — this would have silently broken the
cache the first time it ran). `scripts/seed.py` needed no changes — it already wires foreign keys via
ORM-returned `.id`/name lookups, never a literal integer.

**This section's head pointer above was stale** — nine more migrations had landed after
`133d9b4f9d17` without this doc being updated (`b75496fd203e` through `f8a3c1d9e4b2`: nullable
`payment.order_id`, `is_active` on groups/idols, nullable `lottery_campaigns.draw_at`, and
`direct_sale_campaigns`), none of that history recorded here at the time. Corrected here per
`CLAUDE.md` §9; a fuller rewrite of this section's narrative for everything between
`133d9b4f9d17` and `f8a3c1d9e4b2` is still owed, just not attempted in this pass.

**Current chain head: `a3f7c9e2b6d4`** (`add_password_reset_to_notification_type`) — 52 migrations
total, one linear chain, no branches. **Confirmed applied for real this session**, not just
`py_compile`'d: a fresh local Docker Compose Postgres (empty volume — this ran the *entire* chain
from `f2a3135a19da` forward, not just the newest two) via `docker compose run --rm app python -m
alembic upgrade head` — all 52 migrations ran with no errors, `alembic current` reports
`a3f7c9e2b6d4 (head)`, and a direct `psql \d notifications` / `pg_enum` query confirmed the table
shape and all 8 `notification_type_enum` values (including `password_reset`) match the models
exactly. Went further than a schema check: brought the `app` service up against this same
database and drove the actual notification feature over real HTTP — registered a fan, requested a
password reset, completed it (`POST /profile/set-password`), and confirmed the resulting
`password_reset` notification was real: `GET /notifications/unread-count` → `1`,
`GET /notifications/mine` → the row with the right shape (`type`, all four entity FKs `null`,
`is_read: false`), `POST /notifications/{id}/read` → `is_read: true`, then `unread-count` → `0`.
Also confirmed the new per-route rate limiting actually fires under load: 32 rapid
`GET /notifications/unread-count` calls with one token returned `200` for the first ~29 and `429`
for the rest, matching its `rate_limit(30, 60, user_key)` budget. `docker compose exec app python
-m pytest tests` (unit + integration, against this same live Postgres/Redis) also run — see §3 for
the result. This is meaningfully more verification than this repo has had for most prior
migrations (§3's standing gap was "no live DB reachable most sessions"; this session had one).

## 2. What's built

- **Identity/RBAC**: `users.role`/`company_id`, `management_companies`, `require_admin`/
  `require_manager_or_admin` (`app/deps/auth.py`), company-scoping helpers on every
  company-owned resource's service. `UserOut` (and so `/account/register` and `/profile/me`)
  now returns `role`/`company_id` — previously omitted, so every logged-in user's role was
  invisible to any client reading the API response despite being in the DB. Admins can also now
  create a `role="manager"` account tied to a company directly via `POST /profile/create-manager`
  (`user_service.create_manager_user`) — previously the only ways to get a non-fan account were
  self-register-then-`/make-admin` (admin only, no company) or a raw DB write; there was no path
  to a company-scoped manager account at all short of editing the database.
- **Talent**: `groups`, `idols`, `idol_colors`, `positions`/`idol_positions` — full ORM + schema +
  service + router for all four, company-scoped CRUD.
- **Events & ticketing**: `venues`, `concerts`/`concert_performers`, `ticket_types`,
  `lottery_preferences`, `lottery_campaigns`, `lottery_entries`, `tickets` — full ORM + schema +
  service + router for all seven. `tickets` creation is admin-only (a manual stopgap — see §4).
- **Marketplace**: `categories.is_resale_capped`, `album_details`, `genres`/`album_genres`,
  `merch_details` (originally `lightstick_details`, merged/renamed — item 14) — full ORM + schema +
  service + router.
- **Image uploads**: `idols.profile_image_url` / `products.image_url`, a local/S3 storage
  abstraction (`app/utils/storage.py`), inline upload on `POST /idols/add` and
  `POST /products/add_product` (now `multipart/form-data`, a breaking change from the original
  JSON body), plus `POST /idols/{id}/image` and `POST /products/{id}/image` to replace an image
  later. Full detail: `database-design.md` §9.
- **Seed data** (`scripts/seed.py`): idempotent test-data script — 3 management companies
  (Nova Entertainment, Starlight Media, Kuroyuri Records), 8 users, 5 idol groups spanning
  J-Pop/city-pop/anime-tie-in/gothic/vocaloid-adjacent styles plus 3 solo idols (22 + 3 = 25
  idols total, all Japanese, each with an invented personality blurb), 6 venues (all Japan), 6
  concerts, 18 ticket types across lottery + direct sale methods (priced in yen), 5 categories, a
  20-item marketplace (10 albums/singles/EPs with genres, 8 lightsticks, 2 plain merch items, all
  priced in yen), 2 lottery campaigns with preferences + entries, 1 manually-issued ticket — run
  via `docker compose exec app python scripts/seed.py`. Idol portraits and product covers are
  pushed through the real
  `get_storage().save()` pipeline from `tests/fixtures/{idols,products}/` — procedural
  placeholder art (Pillow gradients/patterns/monograms, no AI image generation was available in
  this environment), not real character art; see `tests/fixtures/README.md`.
- **Notifications** (`app/db/models/notification.py`, migrations `df79d71c6a2c` + `a3f7c9e2b6d4` —
  **applied and live-verified this session**, see §1): a `notifications` table (`database-design.md` §3.19) covering 8
  event types (order/ticket/lottery confirmations, lottery result, payment reminder/confirmation,
  event reminder, password reset), one nullable FK per referenced entity kind. **Now has
  producers**, all inline — no cron/Celery Beat involved anywhere, deliberately (see below):
  `notification_service.create_notification()` is called from inside `order_service.checkout()`
  (`order_confirmation`, success only), `ticket_service.checkout_ticket()` (`ticket_confirmation`,
  success only), `user_service.verify_rtoken()` (`password_reset`), and `lottery_draw_service.
  draw_lottery()` — `lottery_result` for every winner *and* loser, plus `lottery_payment_reminder`
  for winners only, fired once at draw time alongside `lottery_result` (**not** a scheduled
  reminder closer to the payment deadline — that would need a periodic job, out of scope for this
  phase, see §5). Every write lands in the same transaction/commit as the event it describes. Fan-
  facing read/poll API: `GET /notifications/mine` (`?unread_only=true`), `GET /notifications/
  unread-count` (cheap, meant to be polled — no WebSocket/SSE layer exists, see `docs/api-spec.md`
  §7), `POST /notifications/{id}/read`, `POST /notifications/read-all` — self-scoped to
  `current_user.id`, all four now rate-limited (`app/router/notification.py`, previously had
  none). Not yet built: `lottery_registered` (on lottery entry application) and `lottery_payment_
  confirmation`/`event_reminder` have no producer yet — flagged, not implemented speculatively.
  **Also not built, and out of scope for now by explicit decision**: actually emailing any of
  these (see the dedicated note below).
- **Celery skeleton** (`app/celery_app.py`, `app/tasks/`): broker + result backend on the
  existing Redis instance (`CELERY_BROKER_DB`, separate from the cache/rate-limiter's `REDIS_DB`),
  a `worker` service in `docker-compose.yaml`, and a `/start-worker.sh` in the `Dockerfile` for a
  Render Background Worker (`docs/deployment.md` §5). One real task now exists: `app.tasks.lottery.
  draw_lottery` (manager-triggered, §8) — the original placeholder (`app/tasks/example.py`'s
  `ping`) is still there but no longer the only wiring. **No Celery Beat / scheduler is used or
  planned for this phase** — every notification producer above fires inline inside whatever
  request/task caused it, not on a schedule; a periodic job (payment-deadline reminders, an ETL
  sweep) stays open, see §5.

**No email dispatch exists for any notification, and this is a deliberate scope boundary, not an
oversight**: `notifications.status`/`sent_at` sit at their `pending`/`null` defaults forever right
now, because nothing reads a `pending` row and calls SendGrid. The in-app feed
(`GET /notifications/mine`, `unread-count`, mark-read) is fully real — a fan who's logged in can
see every notification listed above the moment it's created — but nothing pushes it to their inbox
if they aren't. Wiring that up for real would mean either (a) a periodic sweep task that queries
`status='pending'` and calls `email_sender.send_email` per row, which is exactly the kind of
cron/Beat job this phase has decided not to build, or (b) sending inline at creation time the way
`user_service.reset_password_process` already does via `BackgroundTasks` — but that only works
inside an HTTP request with a `BackgroundTasks` object in scope, which `draw_lottery` (a Celery
task, not a request handler) doesn't have, so it isn't a drop-in fit for the producer that creates
the most rows (every winner and loser, per concert draw). Either path is a real design decision —
which delivery mechanism, retry/failure handling if SendGrid itself fails, whether a failed send
should block the notification from being marked read — not a small addition, so it's named here as
an open item rather than picked speculatively.
- **12 DB triggers / 8 trigger functions** enforcing the money/fairness invariants
  `database-design.md` §4 lists deliberately (fan-only purchasing, the anti-resale cap, concert
  ticket-capacity, the lottery entry cap, the preference-required check, the lottery
  preference/concert match, the album/lightstick mutual-exclusivity pair).

## 3. Verification method (and its limit)

No live Postgres/FastAPI/network access has been available in most environments this project has
been built in — confirmed repeatedly via failed `pip install` attempts (403 from a proxy). Every
round of changes has instead been verified with:

1. A full `py_compile` sweep across `app/`, `main.py`, and `alembic/`.
2. An AST-based scan of every ORM model's `ForeignKey` targets and
   `relationship(back_populates=...)` pairs (currently: 28 model classes, no issues).
3. An AST-based scan of every intra-app `from app.X import Y` statement, confirming the imported
   name actually exists in its target module (currently: 125 files scanned, no issues).

**One session did have working network access**, and used it to go further than py_compile for
the first time: a full `pip install -r requirements.txt` succeeded, `main.py` imported cleanly end
to end (126 routes registered — confirms every router/service/schema import chain is sound, not
just individually syntax-valid), and `pytest tests/unit` actually ran (against `MagicMock`s, no
real DB — `tests/integration/test_main.py` needs a real Postgres+Redis and was **not** run). That
run found and fixed a real test-isolation bug (`tests/conftest.py` didn't import `app.db.base`,
so whichever test ran first and touched an ORM class could fail purely based on import order —
see git history) and surfaced item 11 above (5 pre-existing stale tests, left as found).

**Still true for everything else**: none of this exercises real SQL or a running app against a
real database. `alembic upgrade head` against a real
Postgres, followed by hitting each endpoint (ideally via `scripts/seed.py`'s data), is still the
outstanding step before any of this should be treated as production-verified — it has not been
done yet for anything built so far, including the ticketing/lottery/marketplace tables and the
image-upload feature.

**Another session with real network/import access, used for the notifications feature**: `import
main` succeeded end to end (129 routes registered, up from 126 — the 3 new `/notifications/*`
routes), and `sqlalchemy.orm.configure_mappers()` was run directly against `app.db.base.Base`
(29 model classes now, up from 28), confirming every FK on the new `notifications` table resolves
to a real target table/column. This project's own local Docker Compose stack
(`postgres`/`redis`/`app`/`worker`) was also found already running and reachable from this
environment — its Postgres is confirmed still at the documented `10f9dfa05636` head — but running
`alembic upgrade head` against it was explicitly not done (user chose to hold off applying the
migration), so **the notifications migration itself was still unverified against a real database
as of that session** — since resolved, see below.

**This session went further than any before it, at the user's explicit request**: no docker-compose
stack was running, so one was brought up from scratch (fresh `postgres_data` volume — an empty
database, not the previously-documented `10f9dfa05636` state) and `docker compose run --rm app
python -m alembic upgrade head` was run for real. Result: all 52 migrations in the chain applied
cleanly end to end, `alembic current` reports `a3f7c9e2b6d4 (head)`, and a direct `psql` query
against `pg_enum`/`\d notifications` confirmed the live schema matches the models exactly (8
`notification_type_enum` values, all 5 FKs, all indexes). Then the `app` service itself was started
against this same database and the notification feature was driven over real HTTP, not just
queried: registered a fan (`POST /account/register`), requested and completed a real password
reset (`POST /profile/forgot-password` → `DEBUG`-mode token in the container logs →
`POST /profile/set-password`), and confirmed the resulting `password_reset` notification through
the actual endpoints — `GET /notifications/unread-count` (`0` → `1`), `GET /notifications/mine`
(the row, correct shape), `POST /notifications/{id}/read` (`is_read: true`), `unread-count` back to
`0`. Also confirmed the new rate limiting under real load: 32 rapid calls to `/notifications/
unread-count` with one token returned `200` for the first ~29 and `429` for the rest, matching its
`rate_limit(30, 60, user_key)` budget exactly. Finally, `docker compose exec app python -m pytest
tests` (unit + integration together, the fuller suite, against this same live Postgres/Redis) —
**339/339 passed**, no regressions. This closes the standing gap for these two migrations
specifically; the rest of the schema (everything before `df79d71c6a2c`) hasn't had this same
live-HTTP treatment, only the `configure_mappers()`/`pytest tests/unit`-against-mocks level from
earlier rounds — the general limitation described above still applies to those.

**A real bug this same live-DB access surfaced: `pytest tests` was running integration tests
directly against the shared dev database** — the one the running `app`/`worker` containers (and
anyone's manual frontend testing, or `scripts/seed.py`) also use. `tests/integration/test_main.py`
has always asserted several endpoints return `404`/empty on a table with zero rows
(`test_list_companies_empty`, `test_list_groups_empty`, `test_get_manager_idols_page_never_404s`,
9 others) — true the first time this test suite ever ran, against a genuinely empty database, and
silently false ever since, the moment any real data (a seed run, a manually-created row) landed in
those tables. Confirmed directly: `pytest tests` on this session's DB — which by then had a full
`scripts/seed.py` catalog (`Sakura Prism`, `Yozora Requiem`, 3 more groups, seeded idols) —
consistently produced exactly these 12 failures, none touching tickets/lottery/notifications, all
failing because real rows existed where the test expected none.

**Fixed at the root — integration tests no longer touch the dev database at all.**
`tests/conftest.py` now redirects `DATABASE_URL` onto a dedicated `<name>_test` database as the
very first thing in the whole test session (before anything imports `app.config.settings`, which
caches whatever `DATABASE_URL` was current at *its* first import for the rest of the process — a
subdirectory conftest would be too late). `tests/integration/conftest.py` then drops, recreates,
and fully migrates that database (`alembic upgrade head`, all 52 migrations) once per test session,
before any integration test module is even imported. Net effect: `pytest tests` is now safe to run
at any time, against any dev-DB state, with a fully deterministic result — it can never see (or
touch) real seeded/manually-created data again, and the 12 previously-flaky failures now pass
reliably (confirmed: `343 passed` — 331 + the 12 — with the same command that used to show
331 passed / 12 failed on a non-empty dev DB). `pytest tests/unit` needed no changes and still
requires no live Postgres at all — the redirect is a pure string rewrite, and the actual
DROP/CREATE/migrate only runs from `tests/integration/conftest.py`, which is never loaded unless
an integration test is actually being collected. One real bug caught building this: `str(url)` on
a SQLAlchemy `URL` object hides the password by default (`hide_password=True`) — the first version
of this fix silently wrote `postgresql://user:***@host/db` into `DATABASE_URL`, which failed
Postgres auth outright rather than connecting to the wrong place; fixed by using
`url.render_as_string(hide_password=False)` everywhere a real connection string is needed. Also
deduplicated `reset_rate_limits` (previously copy-pasted identically in `test_main.py` and
`test_permissions.py`) into one shared autouse fixture in the new `tests/integration/conftest.py`.

## 4. Known issues / tech debt (fix alongside the surrounding code, not standalone)

Ordered roughly by how much each matters to the idol-ticket domain specifically. Items marked
FIXED were pre-existing bugs in the forked boilerplate, closed during this project — not
newly introduced.

1. ~~**Checkout is not one atomic transaction, and has a stock-overselling race**~~ — **FIXED**
   (hand-implemented by the project owner, per the interview-defensibility approach in §6 item 2 —
   the doc text describing this as "still fully unfixed" went stale the moment that commit landed
   and is corrected here, found while investigating an unrelated failing-tests request; not a
   Claude-authored fix). `order_service.checkout()` now: checks the cart total and resale cap
   *before* touching any lock, then takes one `ORDER BY Product.id ... .with_for_update()` lock
   across every needed `Product` row (UUID-ordered — deadlock-safe), checks-then-holds that lock
   through the `Order`/`OrderItem` inserts and `create_payment()` (which no longer commits — see
   its own docstring, "Deliberately does not commit"), and commits exactly once via
   `commit_or_raise()` at the very end, mirroring `ticket_service.checkout_ticket()`'s
   already-fixed pattern (below) instead of the old lock-then-mid-flow-commit shape. Verified by
   reading the current file directly (not assumed) and by the full test suite (`pytest tests/unit`
   + `pytest tests/integration` against the live local Docker Postgres) passing with no
   regressions. **The ticket-domain version of this exact race was fixed first**:
   `ticket_service.checkout_ticket()` (the new direct-sale ticket purchase flow) acquires one
   `with_for_update()` lock on `ticket_type` and holds it continuously through the stock check, the
   `Ticket` insert, `create_ticket_payment()` (deliberately non-committing — see its own
   docstring), and the `sold_quantity += 1` increment, committing exactly once via
   `commit_or_raise()` at the end — no premature commit anywhere in the chain; `checkout()` above
   now follows the same already-proven pattern. Still open: the draw job (§8) needs its own
   concurrency guard designed in from the start, same as always.
2. ~~**The rate limiter's key doesn't include the route**~~ — **FIXED**. `ip_key`/`user_key`
   (`app/cache/rate_limit.py`) previously built their Redis key from only the caller's identity
   (`rate:ip:<ip>` / `rate:user:<id>`), so every endpoint sharing a `key_func` shared one counter
   — a frontend page load firing several `ip_key`-gated GET requests (product list, categories,
   idols, venues, ...) in one burst would exhaust a single shared 60s bucket sized for whichever
   route happened to increment it first, producing 429s that looked unrelated to actual per-route
   traffic. Both key functions now fold in `request.scope["route"].path` (the route's raw path
   template, e.g. `/order/single_placed_order/{order_id}` — not the resolved URL, so different ids
   on the same endpoint still share one budget): `rate:ip:<route>:<ip>` / `rate:user:<route>:<id>`.
   Verified with `py_compile` only, per §3's standing limitation. **Still open**: `ip_key` uses
   `request.client.host` with no `X-Forwarded-For`/`X-Real-IP` handling, so behind any reverse
   proxy (Render, Docker's network, nginx) every visitor could still share one IP-bucket — that's
   a separate fix (and one that needs care, since blindly trusting a forwarded-for header from an
   untrusted network lets a client spoof its way around the limit) not attempted here.
3. ~~`app/db/base.py` didn't import every model~~ — **FIXED**. `Base` now lives in
   `app/db/base_class.py`; `app/db/base.py` is a pure aggregator. See `architecture.md` §5 for
   the convention this establishes going forward.
4. ~~**Webhook handling isn't idempotent**~~ — **moot**. The Paypal integration
   (`payment_service.process_Paypal_webhook`, `verify_Paypal_signature`, the
   `POST /payment/Paypal/webhook` route, the `Paypal` SDK dependency) has been removed —
   real payment gateway integration is deferred to a later phase; only the mock gateway remains,
   and `PaymentGateway` is kept as a single-member enum so a future gateway has somewhere to slot
   in. Whichever gateway lands in that phase will need its own idempotent webhook handler (keyed
   off that provider's event id) designed in before it's allowed to issue tickets — re-derive this
   from that gateway's actual semantics rather than assuming Paypal's.
5. **Minor schema type inconsistencies**: `OrderItem.price` is `Integer` while `Product.price` is
   `Float` (truncates fractional prices in order history); `ShippingAddress.postal_code` is
   `Integer`, which breaks for alphanumeric postal codes (UK, Canada, Japan).
6. ~~**CORS `allow_origins` is hardcoded**~~ — **FIXED**. `main.py` now builds `origins` from a
   new `CORS_ORIGINS` setting (comma-separated, default `http://localhost:8080` to keep local dev
   unchanged) instead of a hardcoded list — set it to the deployed frontend's real origin(s) in
   production. See `docs/deployment.md`.
7. **`cart_service.add_to_cart` doesn't lock the `Product` row** before comparing quantity —
   minor since checkout's own race (item 1) is the real gate, but two concurrent adds can both
   "pass" a stock check that's already stale.
8. **The draw job doesn't exist yet and needs its own concurrency guard** designed in before it's
   built (`SELECT ... FOR UPDATE` while transitioning a campaign `status: open → drawn`) — nothing
   currently stops two runs from processing the same campaign at once.
9. ~~**Trigger errors have nowhere clean to land.**~~ — **FIXED**. `app/exception/db_triggers.py`
   adds `TriggerViolationError` + 8 typed subclasses (one per trigger function), a
   `translate_trigger_error()` that matches a raised `DBAPIError`'s Postgres message against
   each trigger's known wording, and `commit_or_raise()`/`flush_or_raise()` helpers that replace
   a bare `db.commit()`/`db.flush()` at every write a trigger can fire on. Wired into the 8
   service functions that actually reach a trigger-covered insert/update (`cart_service.
   add_to_cart`, `order_service.checkout`, `lottery_entry_service.apply_to_lottery`,
   `ticket_service.add_ticket`, `lottery_preference_service.set_preferences`,
   `ticket_type_service.add_ticket_type`/`update_ticket_type`, `album_detail_service.
   add_album_detail`, `lightstick_detail_service.add_lightstick_detail`) and their 8 routers,
   each now catching `TriggerViolationError` and mapping it via `e.status_code` (403 for the
   fan-only-purchase trigger — an authorization failure — 400 for the other seven). Follows the
   existing `app/exception/checkout.py` convention (raise in the service, catch in the router)
   rather than a global exception handler, for consistency with `docs/architecture.md` §2. Two
   services (`lottery_entry_service`, `lottery_preference_service`) already pre-checked their
   triggers' conditions in Python and return a sentinel instead of ever reaching the DB error in
   normal operation — they're still wrapped, as a defense-in-depth backstop against a race
   between the check and the write, matching how the triggers themselves are documented as
   backstops in `database-design.md` §4.1. Verified with `py_compile` + both AST checks only, per
   §3's standing limitation — no live trigger has actually been fired against a real Postgres to
   confirm the message-matching in `translate_trigger_error()` against real `psycopg2` exception
   text; that's the one part of this fix that a real DB would meaningfully add confidence to.
10. ~~`products`/`categories` still lack company-scoping~~ — **FIXED for `products`**; on
    reflection, `categories` never needed it: every category-mutating endpoint was already
    `require_admin`-only (§4's role table never gives managers category access at all), so there
    was no per-company scoping question to answer there — that half of the original item was a
    misstatement, corrected here rather than carried forward. For `products`: since a product has
    no `company_id` column, `product_service._resolve_product_company_id()` resolves ownership by
    checking whether the product has an `album_details` or `lightstick_details` row and, if so,
    resolving that row's `idol_id`/`group_id` to a `company_id` — the same dual-FK lookup
    `album_detail_service`/`lightstick_detail_service` already used for their own scoping, not a
    new column. `update_product`, `set_product_image`, and `delete_product` now take
    `current_user` and return `"forbidden"` (mapped to 403) when a manager doesn't own the
    resolved company. A product tied to neither table (plain merch with no idol/group) resolves
    to no owner and stays manager-agnostic — this was a deliberate scope decision, not an
    oversight: nothing in the design ever proposed merch belonging to a specific company, so
    "ownerless" is the correct steady state for it, not a gap to close. `add_product`/
    `add_bulk_products` are deliberately left unscoped — a bare `Product` row has no
    idol/group link yet at creation time (that only exists once an `album_details`/
    `lightstick_details` row is attached, through its own already-scoped endpoint), so there is
    nothing to check at creation.

11. ~~**Stale unit/integration tests drifted from production code**~~ — **FIXED**. The original 5
    (`TestProductService::test_update_product_found`/`test_update_product_not_found`/
    `test_delete_product_found`/`test_delete_product_not_found`, `TestCategoryService::
    test_update_category_success`) plus 4 more found in this same pass, all genuine test/production
    drift, not app bugs — the app code was correct in every case:
    - `update_product`/`delete_product` gained a required `current_user` parameter under item 10's
      company-scoping fix; tests updated to pass a mock user (role `"fan"`, so
      `_manager_scope_violation` never fires — only `"manager"` role triggers that check).
    - `test_update_category_success`/`test_update_category_not_found` constructed a `CategoryBase`
      (no `is_resale_capped`) where `category_service.update_category` expects a `CategoryUpdate`;
      switched both to `CategoryUpdate`.
    - `TestCartService::test_add_to_cart_new_item` — item 7's `with_for_update()` lock added to
      `cart_service.add_to_cart`'s existing-cart-row lookup inserted a new mock-chain hop
      (`.filter().with_for_update().first()`) that the test's old shared `side_effect` list on
      `.filter().first()` no longer lined up with, so the mock silently returned a truthy
      MagicMock for "existing cart row found" and the new-item branch (`db.add`) was never
      exercised. Fixed by stubbing the two query chains (product lookup vs. locked cart-row lookup)
      separately.
    - `TestUserService::test_reset_password_process_email_not_found` asserted `result is None` for
      an unregistered email; `reset_password_process` deliberately always returns `True` (item 18's
      anti-enumeration fix, documented in its own comment) so a client response can't be used to
      probe which emails have accounts. Fixed to assert `result is True` and
      `bg_tasks.add_task.assert_not_called()` — actually verifying the anti-enumeration behavior
      instead of asserting a stale, disproven contract.
    - `TestPaymentService::test_create_mock_payment_success`/`test_create_mock_payment_failure` —
      item 16's now-required `idempotency_key` field on `PaymentCreate` wasn't in either test's
      constructor call, so both failed `pydantic` validation before `create_payment` ever ran (and
      the matching `test_checkout_empty_cart` integration test 422'd for the same reason). Fixed by
      supplying `idempotency_key=uuid.uuid4()`; `test_create_mock_payment_success`'s
      `db.commit.assert_called()` was also stale post-item-1-fix (`create_payment` deliberately
      only flushes now, per its own docstring) and was switched to `db.flush.assert_called()`.

    Verified: `pytest tests/unit` (61/61) from the host, and `pytest tests` (86/86 — unit +
    integration) run inside the `app` Docker container against the live local Postgres/Redis
    (`docker compose exec app python -m pytest tests`), since the integration suite needs the
    `postgres`/`redis` service hostnames that only resolve inside that container's network — not
    reachable directly from the host. No app-code changes were needed for any of this; every
    failure was the test suite lagging behind already-correct, already-landed service changes.
12. **Seeded accounts share a hardcoded, publicly-committed password** — `scripts/seed.py`
    creates `admin@example.com` plus three managers and four fans all with the password
    `Password123!`, written in plain text in that file's own docstring in this public repo. Fine
    for a throwaway local dev DB; not fine the moment `scripts/seed.py` is run against a real
    deployed database (see `docs/deployment.md`) — at that point anyone who reads the repo can log
    into the live site as a full admin. Noted, not fixed, per explicit instruction when found —
    before ever seeding a real deployed DB, either randomize the seeded admin/manager password
    (so only the person who ran it knows it) or don't seed that DB at all and rely on read-only
    browsing + `/docs` to demo it. Related, much smaller: `tests/fixtures/README.md` claims
    Pillow is "already a project dependency" — it isn't, `requirements.txt` doesn't list it;
    harmless since `gen_fixtures.py` only ever runs standalone/locally, but the doc line is wrong.

13. ~~**An invalid `category_id` on a product write crashed with a raw 500**~~ — **FIXED**.
    `product_service.add_product`/`update_product`/`add_bulk_products` all set `category_id`
    straight onto a `Product` row and committed with no existence check, so a bad id raised an
    uncaught `IntegrityError` at `db.commit()` instead of a clean 4xx. Found while investigating
    the item below (a manual repro against the live local dev stack — real seed data, real JWT,
    real HTTP call — hit this by accident with a placeholder `category_id`). `update_product`
    returns a new `"category_not_found"` sentinel (mapped to 400 in `products.py`'s router,
    alongside the existing `"forbidden"` case); `add_product`/`add_bulk_products` return `False`,
    which already mapped to 400 with no router change needed. `add_bulk_products` checks every
    referenced category up front (all-or-nothing), not just the first bad one. Verified live
    against the running dev stack, not just `py_compile`: the exact request that previously 500'd
    now returns a clean 400, a valid update on the same product still succeeds, and the
    cross-company 403 from item 14 below still fires correctly (no regression).
14. ~~**Plain "Merch" products have no company ownership at all**~~ — **FIXED, both migration and
    application code landed** (local dev DB only — not yet applied to Supabase, see §1). Originally: any manager could edit/delete a merch
    item whose *name* clearly signalled which company's group it belonged to (e.g.
    `Sakura Prism Tour Hoodie`, seeded under Nova Entertainment's group but with no structural
    link to it) — not a bug in `_manager_scope_violation` (verified live: an **album**-linked
    product from another company correctly got 403), but a real gap in what `_resolve_product_
    company_id` had to resolve against for merch specifically. **Resolution chosen, after
    discussion, over the two other options on the table** (a direct `products.company_id` column;
    a brand-new standalone `merch_details` table): **merge the `Lightstick` category into `Merch`
    and generalize `lightstick_details` into `merch_details`**, rather than build a second,
    near-identical detail table. Nothing in this project's business rules ever actually
    distinguished a lightstick from any other piece of official branded merch — same resale-cap
    treatment, same ownership-resolution shape, same "sold under one clear banner" XOR reasoning —
    so lightsticks already had exactly the mechanism merch needed; the fix generalizes it instead
    of duplicating it. `Album`/`Single`/`EP`/`Merch` (4 categories) is also a more internally
    consistent split than the previous 5, where 4 of 5 buckets were music-related and Lightstick
    was an unexplained carve-out. Full design reasoning: `database-design.md` §3.15/§3.17.
    Migration `b60aec9ffc02` (see §1) is applied locally; application code (model/schema/service/
    router renames, `product_service.py`'s two resolvers, `scripts/seed.py`) landed by hand and is
    verified against the live local DB — 146 routes registered, zero `lightstick` routes remain,
    `pytest tests/unit` shows no regressions. `133d9b4f9d17` (see §1) fixes a follow-on gap
    `b60aec9ffc02` left behind (leftover `lightstick_details_*`-named PK/FK constraints — Postgres
    doesn't rename constraints on `ALTER TABLE ... RENAME TO`), not yet applied anywhere. Neither
    migration has reached Supabase yet — this item is fixed for local dev only until it does.

15. ~~**`DELETE /profile/delete` 500'd for any user with a `shipping_addresses` row**~~ —
    **FIXED**. `Users.shippingadd`/`cart`/`user_order`/`paymentuser` (`app/db/models/user.py`)
    had no `passive_deletes`, so on `db.delete(db_user)` SQLAlchemy's default unit-of-work tried
    to `UPDATE ... SET user_id = NULL` on each child row before deleting the parent — which
    raised a `NotNullViolation` since `shipping_addresses.user_id`/`cart.user_id`/
    `orders.user_id`/`payment.user_id` are all `NOT NULL`, even though their FKs already declare
    `ON DELETE CASCADE` at the DB level (see each table's migration). Fixed all four
    relationships the same way (not just `shippingadd`, which is all the reported repro hit) by
    adding `passive_deletes=True`, so SQLAlchemy skips the nullify step and lets Postgres's
    existing cascade handle it. Verified live against the running dev stack (not just
    `py_compile`): registered a fresh fan, added a shipping address, `DELETE /profile/delete` now
    returns a clean 200, and both the `users` and `shipping_addresses` rows are confirmed gone
    from Postgres afterward.

16. ~~**No client-retry idempotency on either checkout endpoint**~~ — **FIXED** (hand-implemented
    by the project owner; doc corrected here after being found stale during an unrelated
    failing-tests investigation — not a Claude-authored fix). Built essentially as recommended
    below: `payment.idempotency_key` is now a `UUID NOT NULL UNIQUE` column (two migrations —
    added nullable, backfilled, then tightened to `NOT NULL`, one concern each), `PaymentCreate`/
    `TicketCheckoutCreate` both require it from the client, and `order_service.checkout()`/
    `ticket_service.checkout_ticket()` each check `Payment.idempotency_key` for a match *before*
    doing anything else, raising `DuplicateIdempotencyKeyError` (`app/exception/db_triggers.py`,
    mapped through the same `TriggerViolationError`/`commit_or_raise` machinery as the DB-trigger
    backstops) rather than silently creating a second `Payment` row. A double-click or retry that
    resends the same client-generated key now gets a clean rejection instead of a duplicate mock
    charge. Verified by the full test suite passing (`tests/unit` + `tests/integration` against the
    live local Docker Postgres) — not yet verified with a real concurrent-retry repro against a live
    DB, which would be the next confirming step if this is revisited.

17. ~~**`delete_group`/`delete_idol` hard-deleted the row**~~ — **FIXED**. `groups.id` and
    `idols.id` are FK targets with real cascade behavior: `concert_performers.idol_id`/`.group_id`
    are `ondelete="CASCADE"` (a hard delete silently wiped the performer record for concerts that
    already happened) and `album_details`/`merch_details`' `idol_id`/`group_id` are
    `ondelete="SET NULL"` (a hard delete orphaned artist attribution on products with real order
    history). Both services now soft-delete: a new `is_active BOOLEAN NOT NULL DEFAULT true`
    column (migration `a1f3c9d27e56`, same shape as the pre-existing `users.is_active`) is flipped
    to `false` instead of `db.delete()`, with a matching `reactivate_group`/`reactivate_idol` +
    `PATCH /groups/activate/{id}` / `PATCH /idols/activate/{id}`. Store-facing reads (`get_groups`,
    `get_idols`, `get_groups_page`, `get_group_detail`, `get_idol_detail`, `get_members_page`)
    filter to `is_active=True`; manager/admin settings reads (`get_manager_groups_page`,
    `get_manager_idols_page`, `get_manager_idol_form_page`) and the plain by-id lookups
    (`get_group`, `get_idol`) deliberately don't, so a manager's edit form can still load a
    deactivated row to reactivate it. Historical joins (concert performer credits, product artist
    resolution in `product_service.py`) query `Group`/`Idol` directly and were left unfiltered on
    purpose — that's the data soft-delete was meant to preserve.

    Four follow-on judgment calls, resolved explicitly rather than left implicit: **(1)** filtering
    is the store-vs-manager split above, not per-endpoint. **(2)** deactivating a group does **not**
    cascade to its idols — matches the existing "membership is independent, `group_id IS NULL` for
    solo idols" framing; an idol keeps its `group_id` untouched when its group goes inactive.
    **(3)** a deactivated idol/group is closed to *new* attachments: `idol_service.add_idol`/
    `update_idol` reject assigning an idol into an inactive group (`"group_inactive"`, 400 —
    `update_idol` only rejects a genuine reassignment, not an unchanged `group_id` resent by the
    full-replace `PUT` after the group was deactivated later), and
    `album_detail_service.add_album_detail`/`merch_detail_service.add_merch_detail` reject
    attaching a new release/merch item to an inactive idol or group (`"artist_inactive"`, 400) —
    existing members/releases are untouched, only new ones are blocked. **(4)** reactivation is
    `PATCH /groups|idols/activate/{id}`, not a field on the general-purpose `PUT /update` — putting
    `is_active` on `GroupUpdate`/`IdolUpdate` would let it get silently reset to its Pydantic
    default on any unrelated field edit, since neither `Update` schema is a partial/`PATCH` body.

    Verified with `py_compile`, plus (network access happened to be available this session) `import
    main` + `sqlalchemy.orm.configure_mappers()` end to end (150 routes, including the 2 new
    `PATCH .../activate/{id}` routes) and `pytest tests/unit` (53/61 passing, the 8 failures are
    pre-existing/unrelated `idempotency_key` schema changes — item 16 — not this feature; no
    group/idol unit tests exist yet, so nothing regressed there specifically). **Not** run against
    a live Postgres — `alembic upgrade head` + hitting the endpoints for real is still the
    outstanding step, same standing gap as everything else in this section.

18. ~~**Verification/reset tokens had no dev-visible surface**~~ — **FIXED**. Frontend flagged
    that `SENDGRID_API_KEY` is a placeholder in local dev (per `.env.example`), so
    `email_verification_process`/`reset_password_process` always fail to actually deliver — and
    since `send_email` runs via `BackgroundTasks` *after* the response, the failure (and the token
    inside the unsent email) had nowhere visible to land. New `settings.DEBUG` flag (default
    `false`): when `true`, `app/utils/email_sender.py`'s `send_email` prints the full email body —
    token included — to the console before attempting the real SendGrid call, and now always
    catches that call's exception instead of letting it raise unhandled inside the background
    task. Deliberately **not** solved by returning the token in the API response instead: `POST
    /profile/forgot-password` is intentionally anti-enumeration (identical response whether or not
    the email is registered, per its own comment in `user_service.py`) — putting a real token in
    the response only for matched accounts would reopen that exact side channel, even in dev.
    `DEBUG` must stay unset/`false` in production (documented in `deployment.md`'s env var table)
    since these bodies carry live auth tokens. Verified with `py_compile` and `import main` +
    `configure_mappers()`; not exercised against a live SendGrid call either way.

19. ~~**A fan could hold both a direct-sale ticket and an active lottery claim on the same
    concert**~~ — **FIXED**. Two gaps, both service-layer (neither is a money/fairness invariant in
    §4.1's trigger-worthy sense): `lottery_entry_service.apply_to_lottery` didn't check whether the
    fan already held a live ticket for the concert (`Ticket.status` in `reserved`/`pending_payment`/
    `paid`/`used`) before letting them apply to another tier's lottery on top of it — now returns a
    new `"already_has_ticket"` sentinel (400) if so, checked right after resolving the campaign's
    `ticket_type`, before the preference/cap checks. `ticket_service.checkout_ticket` didn't check
    the fan's lottery standing for the concert at all before letting them buy `direct` — now raises
    a new `LotteryEntryUnresolvedError` (`app/exception/checkout.py`, a plain `CartItemError`
    subclass, so no new router `except` clause was needed — it falls through to the existing generic
    400 handler) if any of their `lottery_entries` for that concert are still `pending` or `won`;
    only `lost` (or no entry) clears it. The `won`-without-a-live-ticket case is the one
    `trg_tickets_one_per_concert`/`_existing_live_ticket` alone can't catch: a fan who won a tier but
    let the resulting ticket's `payment_deadline_at` lapse (`status` → `expired`) no longer holds a
    live ticket, but their entry is still `won` — this closes that gap specifically. Full reasoning:
    `database-design.md`'s `ticket_types` section (§3.8-adjacent). Verified for real against the
    live local Docker Postgres: 4 new integration tests in `tests/integration/test_permissions.py`
    (already-has-ticket blocks lottery apply; pending/won lottery entries block direct checkout;
    lost does not) over real HTTP against real fixture rows, not mocks — all 4 pass, and the full
    `test_permissions.py` file (42 tests) passes with no regressions. A full `pytest tests` run in
    the same session also showed 331 passed / 12 failed — **the 12 failures were pre-existing and
    unrelated to this fix** (none touch tickets, lottery entries, or notifications; root cause was
    the test suite running against the shared, non-empty dev database — since fixed for real, see
    §3's dedicated writeup and item 20 below).

20. ~~**`pytest tests` ran integration tests directly against the shared dev database**~~ —
    **FIXED**. Full writeup in §3. `tests/conftest.py` redirects `DATABASE_URL` onto a dedicated
    `<name>_test` database (a pure string rewrite, so `pytest tests/unit` still needs no live
    Postgres at all); `tests/integration/conftest.py` drops, recreates, and fully migrates that
    database once per session before any integration test can touch it. This was the actual cause
    of the `test_main.py` `*_empty`/`*_never_404s` failures documented as "pre-existing" in items
    18-19 above and in earlier `pytest tests` runs this project has logged — not 12 separate app
    bugs, one shared root cause, now closed. Also deduplicated the identical `reset_rate_limits`
    fixture out of `test_main.py`/`test_permissions.py` into one shared autouse fixture in the new
    `tests/integration/conftest.py`. Verified: `343 passed` (`pytest tests`, unit + integration
    together) against a database seeded with a full `scripts/seed.py` catalog beforehand,
    confirming this can never again see or touch real dev/seed data — plus a direct check that the
    real dev database's row counts were unchanged after the test run.

Several smaller items from the original boilerplate audit (UTF-16 `requirements.txt`, a
category-update authorization bug, secrets traveling as query params, no `.dockerignore`, a
missing `UNIQUE` on `Category.name`) were found and fixed earlier in this project and aren't
repeated here — see git history / earlier `CLAUDE.md` versions if the detail is needed.

## 5. Deliberately deferred — next phase, not forgotten

- **Payment failure handling** — the mock gateway's decline path (`simulate_succ=false`) has
  always worked; PayPal's decline path (`finalize_paypal_payment`'s `else` branches, §7) is
  implemented but not yet exercised against a real declined sandbox payment.
- **The direct/"reservation" (non-lottery) checkout flow** — the schema supports it
  (`ticket_types.sale_method = 'direct'`), but only the lottery path has a sequence diagram
  (`database-design.md` §5.2) and only `tickets`' admin-only manual-issue endpoint exists so far.
- **The draw job's actual runtime** — **decided: manager-triggered**, not a Celery Beat scheduled
  task — see §8 for the full plan. The Celery skeleton (`app/celery_app.py`, broker on Redis)
  stays unused for this specific job as a result; it may still end up used for winner-notification
  dispatch (a separate concern from the draw itself, see §8).
- **UI messaging** for "you can't apply to this lottery because you haven't ranked that tier yet"
  — the application is correctly rejected server-side; there's no client-facing nudge designed.
- **`idols.real_name`** — deliberately left unmodeled.
- **ETL / data pipeline** — the project brief's other major goal alongside architecture, not
  started. Natural source events (ticket purchases, lottery entries + draw outcomes, payment
  webhooks, shipment status changes) should probably feed an outbox/event table
  (`domain_events`: type, payload, occurred_at, processed flag) written in the same transaction
  as the business write, rather than a future job scraping OLTP tables or polling `updated_at`.
  Candidate downstream shape: periodic transform into analytics-friendly fact tables
  (`fact_sales_by_concert`, `fact_lottery_conversion`, `fact_fan_activity`) in either a separate
  schema in the same Postgres instance or a real warehouse if scope grows. Don't design the fact
  tables before the OLTP shape settles further — with `lottery_entries.source_order_item_id`
  removed (`database-design.md` §3.13), a lottery entry no longer carries purchase context, which
  is worth resolving before this gets built, not after.
- **Product "personality"** — the brief's third goal (tone of copy, idol/fandom-specific
  flourishes, branding on `/docs`, error messages, email templates). `idol_colors`' pastel palette
  is the one seed of it so far; nothing else is designed. Don't invent details speculatively —
  flag it in the next planning conversation.
- **`schema.sql`** — cited throughout `database-design.md` as if it exists; it doesn't (§1 above).
  Either generate one from the live migrations/models, or stop citing it and treat the migrations
  themselves as the reference DDL.
- **Every product must be owned (have an `album_details` or `merch_details` row) — proposed, not
  designed, not implemented.** Today an ownerless product is a fully legitimate, permitted state
  by design (`database-design.md` §3.15/§6) — nothing enforces or even flags it, which is exactly
  what let item 14's bug exist in the first place. Making ownership *required* rather than merely
  *possible* is a real policy change, not a bug fix, and it runs straight into a structural
  conflict worth resolving before it's built, not while building it: product creation is
  deliberately two-step today (`POST /products/add_product` creates a bare `Product` with
  nothing to check yet; a *separate* `POST /album_details/add` or `POST /merch_details/add` call
  attaches ownership afterward — see `product_service.py`'s own comment on why `add_product`/
  `add_bulk_products` are deliberately unscoped). A hard "must be owned" rule can't be enforced at
  the moment of creation without also redesigning that flow to be atomic (one call creates both
  rows together, or the two inserts happen in one transaction with a `DEFERRABLE INITIALLY
  DEFERRED` constraint checked at commit — the latter only works if the API stops being two
  separate HTTP requests). Softer alternatives that don't require touching the creation API:
  a `products.status` (`draft`/`published`) gate that only requires ownership before a product
  becomes publicly visible, or a periodic audit query (see the diagnostic SQL from this session)
  with no DB-level enforcement at all — visibility instead of a hard constraint. Also genuinely
  undecided: does this apply to *every* product, meaning there's no such thing as legitimate
  platform-level/unbranded merch anymore, or does some category of product get to stay
  intentionally ownerless on purpose? Don't pick an enforcement mechanism or a scope answer
  speculatively — this needs its own design pass, the same way the checkout-transaction fix did,
  before any of it gets built.

## 6. Suggested next steps, in order

1. A real `alembic upgrade head` + endpoint smoke test against live Postgres/Redis — the
   standing gap behind every "verified" claim in this project so far (§3), and now the specific
   thing that would confirm §4 item 9's trigger-message matching actually works against real
   Postgres error text, not just AST/compile checks.
2. ~~Fix the checkout/ticket-inventory race (§4 item 1) before building the draw job or direct
   purchase flow on top of it~~ — **DONE**, see §4 item 1. `order_service.checkout()` now takes a
   single `ORDER BY Product.id ... FOR UPDATE` lock across every needed row and commits once at
   the very end via `commit_or_raise()`; `create_payment` stayed named `create_payment` (not
   renamed to `_create_payment` as originally sketched here) but is otherwise the non-committing
   internal step this plan called for. Hand-implemented by the project owner (interview-
   defensibility reasons), not done by Claude.
3. Build the draw job (§5/§8), with its concurrency guard designed in from the start.
4. ~~Fill in the missing *primary* fan-only-purchase check at the service layer~~ — **FIXED**.
   `cart_service.add_to_cart`, `order_service.checkout`, `lottery_entry_service.apply_to_lottery`,
   and `ticket_service.add_ticket` each now check the buyer's (or, for `add_ticket` — admin-only,
   see §2 — the ticket's intended owner's) `role == "fan"` before doing anything else.
   `add_to_cart`/`checkout` raise `FanOnlyPurchaseError` directly (already existed for the trigger
   backstop, `app/exception/db_triggers.py` — reused rather than adding a new exception, since both
   files are already exception-based and both routers already catch `TriggerViolationError`
   generically, so **no router change was needed for either**). `apply_to_lottery`/`add_ticket`
   return a new `"fan_only"` sentinel instead, matching each function's existing string-sentinel
   convention for its other pre-checks — `lottery_entry.py`/`ticket.py`'s routers each gained one
   new branch mapping it to 403. Verified for real (not just `py_compile`): mocked-session
   behavioral checks confirmed all four reject a non-fan before touching any other table and let a
   fan fall through unaffected, and the existing `tests/unit` suite was actually run —
   56/61 passing, the 5 failures are the pre-existing, already-documented item 11 tests, unrelated
   to this change. One test-fixture gap found and fixed along the way: `make_mock_user()`
   (`tests/unit/test_services.py`) never set `.role` at all, which would have broken
   `add_to_cart`'s two existing tests once a real role check existed — given a `role="fan"` default,
   matching `Users.role`'s actual DB default.

## 7. PayPal gateway integration — implemented, partially verified

Hand-implemented by the project owner (interview-defensibility reasons, same as §6 item 2: real
gateway integration, webhook idempotency, and signature verification are exactly the class of
correctness problem this portfolio is meant to demonstrate judgment on), reviewed by Claude across
several rounds. This is the item §4 item 4 and §5 referred to as "next-phase work."

**The core problem the previous, removed PayPal integration (§4 item 4) didn't solve**: the mock
gateway resolves success/failure synchronously inside `checkout()`/`checkout_ticket()` via a
`simulate_succ` flag. PayPal can't work that way — it's an async three-step handoff (create order →
buyer approves in PayPal's UI → server captures) plus a webhook that can arrive before, after, or
instead of the capture call, possibly more than once. This is solved: stock/seat decrement happens
only inside `finalize_paypal_payment` once payment is *actually* confirmed, not at checkout time;
the capture endpoint and the webhook handler are two entry points into that one shared function,
not duplicated logic; and re-running `finalize_paypal_payment` against an already-resolved payment
is a no-op (`payment.status != PaymentStatus.pending` guard, first check in the function) — the
idempotency mechanism ended up being that status guard rather than a separate event-id table (see
"deviations from the original plan" below).

**What actually shipped**, roughly matching the original ordered plan:
1. `app/config/settings.py`: `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_MODE`
   (`sandbox`|`live`), `PAYPAL_WEBHOOK_ID`, `BASE_URL`. No new dependency — `httpx` only.
2. `app/utils/paypal_client.py`: `get_access_token()` (OAuth2 client-credentials, cached
   in-process), `create_order(amount, currency)`, `capture_order(paypal_order_id)`,
   `verify_webhook_signature(headers, body)` (posts back to PayPal's own
   `/v1/notifications/verify-webhook-signature` rather than reimplementing cert-chain verification),
   `extract_approval_url(order_response)` (pulls the buyer-facing `payer-action`/`approve` HATEOAS
   link out of `create_order`'s response).
3. Migrations: `d4e6f2a8c1b9` adds `'paypal'` to `payment_gateway_enum`; `e8b4a1f0c5d7` adds
   `payment.pg_approval_url` (persists the link `extract_approval_url` returns, so a frontend can
   read it back off `PaymentResponse` without re-deriving it) — **not yet applied to a live
   database from this session's environment** (`alembic upgrade head` needs the `postgres` Docker
   host, unreachable from outside the compose network); run it before relying on
   `pg_approval_url`.
4. `PaymentGateway.paypal` in `app/schema/payment.py`; `PaymentResponse.pg_approval_url` added.
5. `order_service.checkout()`/`ticket_service.checkout_ticket()`'s `paypal` branch: creates the
   Order/Ticket row pending, calls `create_order()`, stores `pg_order_id` + `pg_approval_url` — no
   stock decrement yet. `finalize_paypal_payment(db, pg_order_id, user_id)` in `payment_service.py`
   re-locks the relevant rows (`with_for_update()`), check-then-decrements stock/capacity *before*
   calling `capture_order()` (an irreversible external side effect — checking after would let
   PayPal successfully take a buyer's money for an order that turns out unfulfillable), then marks
   `Payment`/`Order`/`Ticket` success and commits once. Two router endpoints in
   `app/router/payment.py`: `POST /payment/paypal/capture/{pg_order_id}` (fast path, authenticated)
   and `POST /payment/paypal/webhook` (reconciliation path, signature-verified, no auth).
   `GET /payment/paypal/return` and `/cancel` are placeholder JSON responses standing in for the
   frontend routes PayPal's `return_url`/`cancel_url` need once one exists — see
   `docs/api-spec.md` §6 "PayPal checkout flow" for the full frontend-facing sequence.

**Deviations from the original plan**:
- The planned `processed_webhook_events` table (idempotency keyed on PayPal's event `id`) was
  dropped — `payment.status != PaymentStatus.pending` already makes `finalize_paypal_payment`
  idempotent regardless of which caller (capture endpoint or webhook) reaches it first or how many
  times the webhook re-delivers, without a second table to maintain.
- `finalize_paypal_payment`'s webhook branch extracts `pg_order_id` from
  `resource.supplementary_data.related_ids.order_id` — this was an unverified guess when written;
  it's since been confirmed correct against a real `PAYMENT.CAPTURE.COMPLETED` sample payload from
  PayPal's own webhook simulator.

**Verified so far**: a real PayPal Sandbox ticket checkout end-to-end — create order → approve on
PayPal's sandbox UI → `POST /payment/paypal/capture/{pg_order_id}` → `Payment`/`Ticket` both flip to
success/paid correctly.

**Not yet verified — known limitations, not silently assumed working**:
- **The order-flow (marketplace) checkout has not been run end-to-end against real PayPal** — only
  the ticket flow has. The code path is the same shape (see §7 point 5 above) and has been
  reviewed, but "reviewed" isn't "observed working."
- **The webhook path has never received a real or simulated delivery.** Both a real ngrok-forwarded
  webhook and PayPal's own webhook-simulator "Send Test" were tried; ngrok's inspector shows zero
  incoming requests either way, despite the tunnel being confirmed live and the registered webhook
  URL confirmed to exactly match it. This lines up with a documented, PayPal-side pattern (their
  developer community reports the simulator saying "queued" and never delivering, and PayPal is
  known to silently drop delivery to domains it flags as tunnel/abuse-associated, which
  `*.ngrok-free.dev` plausibly is) rather than a bug in `verify_webhook_signature` or the route
  itself — but this is inference, not confirmation. If this matters later: try swapping the local
  tunnel to `cloudflared` (different domain, no interstitial) before assuming the handler code is
  at fault.
- **The decline path** (`finalize_paypal_payment`'s `else` branches, marking `Payment`/`Order`/
  `Ticket` failed/cancelled) has been code-reviewed but not exercised against a real declined
  sandbox payment.
- **No sweep for abandoned PayPal checkouts** — a `pending` order/ticket whose buyer never
  approves or cancels stays `pending` indefinitely; nothing expires it or frees the stock it never
  actually decremented (it never decremented stock in the first place, so no inventory is
  incorrectly held — but the row itself lingers). Whether that needs an expiry job is still an open
  question, not a decided no.
- Whether `finalize_paypal_payment` needs a lock against being invoked concurrently by both the
  capture endpoint and the webhook for the same order was flagged as open in the original plan;
  the `with_for_update()` row locks plus the pending-status idempotency guard appear to close this
  in practice (whichever caller wins the row lock first resolves the payment; the second sees
  `status != pending` and returns `None`), but it hasn't been deliberately race-tested.

## 8. Planned next: manager-triggered lottery draw job

**Design drafted, not yet implemented** — deliberately left for hand-implementation (interview-
defensibility reasons, same as §7: concurrency guarding a multi-table business algorithm is exactly
the class of judgment this portfolio is meant to demonstrate, not infrastructure to have generated).
Resolves §4 item 8 / §5's "draw job's actual runtime is unchosen" and §6 item 3.

**Runtime decided: a company manager (or admin) triggers the draw via an HTTP action, scoped to
their own company's concerts** — not a Celery Beat cron on `lottery_campaigns.draw_at`. Chosen
specifically so the RBAC/company-scoping story this project tells everywhere else (`groups`/`idols`/
`concerts`/`ticket_types`/`lottery_campaigns`) extends to the draw itself, and so there's a
accountable human action instead of an unattended scheduled job for something that reserves
inventory. `draw_at` stays on the schema as the fan-facing ETA; it does not have to be the instant
the draw actually runs (see the open question below).

**Refined: the trigger endpoint enqueues a Celery task rather than running the algorithm inline
in the request.** The draw touches every campaign/entry/preference/ticket_type row for a concert —
not something that belongs in an HTTP request/response cycle. `app/celery_app.py`'s `include` list
only registers `app.tasks.example` today; an untracked `app/tasks/lottery.py` placeholder already
exists (`draw_lottery`, mirrors `example.py`'s `ping` shape) but **isn't wired into `include` yet**,
so the worker wouldn't discover it as-is — first concrete gap to close. The router's job stays
synchronous and small: validate the concert/RBAC, confirm at least one campaign is actually `open`,
then `draw_concert_lottery.delay(concert_id)` and return `202` with a "queued" message — no task-id
polling endpoint needed, since a manager can just re-`GET` the campaign(s) and watch `status` flip
`open` → `drawn`, reusing an endpoint that already exists rather than building new status-tracking
infra. The task itself opens its own DB session directly via `app.db.session.session()` (not
FastAPI's `get_db` generator, which only exists inside a request) and calls straight into
`lottery_draw_service`'s algorithm below. The row-level `FOR UPDATE` + `status='open'` guard already
designed in makes this safe even if two managers' clicks enqueue two messages for the same concert —
Postgres serializes on the row lock regardless of which worker process picks each message up, so
nothing extra is needed at the Celery layer for that case.

**Trigger granularity: per concert, not per campaign.** `lottery_campaigns` is one row per
`ticket_type` (one tier), but `database-design.md` §5.2's rank cascade requires every tier's
campaign for one concert to be drawn together — a fan's "at most one ticket per concert" guarantee
depends on the cascade seeing every tier's pending entries at once. A per-campaign trigger would let
a manager draw VIP while Premium/Regular are still open, breaking that guarantee. Endpoint:
`POST /lottery_campaigns/concerts/{concert_id}/draw`, added to the existing
`app/router/lottery_campaign.py` (same `require_manager_or_admin` + string-sentinel/`_raise_for`
convention already there), draws every `status='open'` campaign under that concert's ticket types
as one atomic unit.

**RBAC**: concerts already carry `company_id` directly, so this is the same one-level
`_manager_scope_violation(current_user, concert.company_id)` check `concert_service`/
`ticket_type_service` use — simpler than `lottery_campaign_service`'s own two-level
(`ticket_type_id` → `concert_id`) join, since the trigger works from the concert side.

**Concurrency guard** (same shape as the checkout fix and `ticket_service.checkout_ticket`'s
existing pattern): `SELECT ... FOR UPDATE ORDER BY id` on every target `lottery_campaigns` row for
the concert (UUID-ordered, deadlock-safe) plus `with_for_update()` on the `ticket_types` rows whose
`sold_quantity` the draw will increment. Only `status='open'` campaigns are eligible, which makes
the endpoint self-idempotent — a double-click or a race between two managers finds nothing open on
the second call and returns a clean "already drawn" instead of re-running the draw.

**Algorithm** (maps directly to `database-design.md` §5.2's sequence diagram — full walkthrough with
a worked example was covered in conversation, not reproduced here): reject if any target campaign's
`entry_end_at > now()`; then for `rank = 1, 2, 3, ...`, gather every tier's `pending` entries whose
user ranked that tier at this rank and hasn't already won elsewhere in this concert this run, sample
winners up to each tier's remaining `total_quantity - sold_quantity`, mark them `won` + insert a
`Ticket(status='pending_payment')` + increment `sold_quantity`; after the last rank, every entry
still `pending` becomes `lost`; flip all processed campaigns to `status='drawn'`; one commit at the
end (`commit_or_raise`) — not the mid-flow-commit pattern `order_service.checkout` is still broken
by.

**Randomness source — decided**: use `secrets.SystemRandom().sample(candidates, k)`, not the
default `random` module or Postgres's `ORDER BY random()`. The business rule ("no purchase
multiplier, no bulk-buy bonus — every fan gets exactly one shot", §5.2) already fixes the *method*
as uniform sampling — nothing to weight by, so no custom selection algorithm is needed. What's
worth getting right is the *source*: the default `random`/`random()` PRNGs are Mersenne-Twister-
class, statistically uniform but not cryptographically secure — in principle reconstructible from
enough observed outputs. `secrets.SystemRandom()` is OS-CSPRNG-backed and a drop-in replacement, so
there's no real cost to making a fairness-critical selection unpredictable rather than merely
uniform. Sampling runs in Python (not SQL) since the cross-rank/cross-tier exclusion bookkeeping is
already inherently procedural, not expressible as one query.

**Update — partially built, not fully deferred any more**: the *in-app* notification rows (§2's
Notifications bullet) now ARE written inside this job's own transaction — `draw_lottery` calls
`create_notification()` for `lottery_result` (every winner and loser) and, for winners only,
`lottery_payment_reminder` (fired once, at draw time, alongside `lottery_result` — not a scheduled
nag closer to the deadline) — all before its one `commit_or_raise()`, since these are cheap
same-database inserts, not external calls, so coupling them to the draw's commit costs nothing and
buys atomicity (no "drew winners but the notification write failed separately" gap). What's still
genuinely deferred, and out of scope for this phase specifically: a *second*, deadline-proximity
reminder (that would need a periodic scan — a cron/Celery Beat job, deliberately not built this
round) and actually *emailing* any notification at all (see §2's dedicated note — `notifications.
status`/`sent_at` stay at their `pending`/`null` defaults forever right now). A reproducible/
auditable draw (logging a seed + candidate snapshot per rank so a disputed
result could be replayed) was considered and intentionally **not** planned in — nothing in this
project's scope models a dispute process, and CLAUDE.md §7 flags exactly this kind of speculative
scope addition to avoid; worth naming if asked, not worth building.

**Placement**: new `app/services/lottery_draw_service.py` rather than folding into
`lottery_campaign_service.py` — the draw is a meaningfully different concern (the "Job" actor in
§5.2, touching `LotteryCampaign`/`LotteryEntry`/`LotteryPreference`/`TicketType`/`Ticket`) from plain
campaign CRUD, and keeping it separate makes the interview-relevant file easy to point at directly.

**Open question, not decided yet** — resolve before implementing, don't pick speculatively: does the
endpoint gate only on `entry_end_at` (entries closed, manager has full discretion on exact timing —
the option that actually justifies a human trigger over a cron) or also require `now() >= draw_at`
(manager trigger becomes "confirm/kick off" rather than full discretion)? Leaning toward the former
but this changes what `draw_at` means in the schema's story, so it isn't mine to decide.

**Verification plan**: same standing gap as everything else in §3 — no live Postgres has run this;
`alembic upgrade head` + a real multi-fan draw against seeded data (`scripts/seed.py`'s 2 lottery
campaigns) is the confirming step once implemented, not just `py_compile`.
