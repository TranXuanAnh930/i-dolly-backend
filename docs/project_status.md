# Project Status

A snapshot of what's built, what's verified, and what's still open — read this before assuming
something exists or is finished. `database-design.md` (same folder) is the schema/business-logic
design; `architecture.md` is how the code is organized; this file is the "where are we right
now" layer, and the one most likely to go stale — update it whenever a feature actually lands or
a known issue gets fixed, don't let it drift into aspirational state.

## 1. Current migration state

**Chain head: `a9d3f5b7c1e2`** (`unique_shipping_status_order_id`) — 62 migrations,
one linear chain, no branches. Up through `a3f7c9e2b6d4` (`add_password_reset_to_notification_type`),
applied and confirmed against a real Postgres instance: `alembic upgrade head` ran clean from
empty, `alembic current` reported the head revision, and the `notifications` table/enum matched
the models. The notification feature was also exercised over real HTTP end to end (password reset
→ notification created → read → unread-count clears), and the per-route rate limiter was confirmed
firing under load (a 30/60s budget returns `429` past the 30th request). The app is now also
deployed against a real Supabase Postgres (§3) — migrations run clean there through the current
head. `54347349d0f2` and `bfadb696c92a` (item 5's schema-type fix) have only been verified
statically (`py_compile`, `alembic`'s own revision-chain check) so far, not yet re-run against
Supabase. `c7f2a4d8e1b5` and `d3a9e5f1c8b7` *were* re-run against a throwaway Postgres database
(the seed/verification pattern used throughout this doc): `alembic upgrade head` from empty landed
clean each time, and `enum_range(NULL::notification_type_enum)` confirmed `lottery_draw_triggered`/
`lottery_draw_failed` present — see the Notifications bullet in §2 below for the three new
producers these added. `d3a9e5f1c8b7`'s producer specifically was exercised past just the enum:
calling `draw_lottery_task` directly against that same database with a concert whose lottery
campaign hadn't closed yet confirmed the `BadRequestError` propagates and the `lottery_draw_failed`
row lands, in one run. `7c7c3f5e19fc` (`add_lottery_draw_completed_to_notification_type`),
`e4f8b2a6c9d1` (`drop_album_details_cover_image_url`), and `f1a7c3e9b5d2`
(`add_order_shipped_to_notification_type`, this session's shipping-status work, item 43), and
`a9d3f5b7c1e2` (`unique_shipping_status_order_id` — adds a unique constraint, item 43)
have only been verified statically (`py_compile`, `alembic`'s own revision-chain check) so far — Docker
Desktop's engine was unreachable at the time. **Since run live (2026-09-25):** the integration
suite's `alembic upgrade head` from empty applied all four cleanly (235/235 tests passed).

All 18 domain tables from `database-design.md` plus the pre-existing e-commerce tables are
migrated. `schema.sql`, cited throughout `database-design.md` as "the reference DDL," doesn't
exist as a file in this repo — every migration was written directly against the design doc, not
transcribed from a DDL file. Generate one from the live migrations/models if it's ever needed.

Every primary/foreign key is a UUID, not a sequential integer, for enumeration resistance. This
touches every model, migration, schema, router/service id parameter, JWT `sub` claim handling, and
the product-list Redis cache (`p.id` is stringified before `msgpack.packb`, since msgpack has no
native UUID type).

The `lightstick_details` → `merch_details` rename (`b60aec9ffc02`) initially missed 5
Postgres-auto-named constraints (the primary key and all 4 foreign keys, never explicitly named in
the original migration) since `ALTER TABLE ... RENAME TO` doesn't touch constraint names —
`133d9b4f9d17` renames the rest. See `database-design.md` §3.17.

## 2. What's built

- **Identity/RBAC**: `users.role`/`company_id`, `management_companies`, `require_admin`/
  `require_manager_or_admin` (`app/deps/auth.py`), company-scoping helpers on every
  company-owned resource's service. `UserOut` returns `role`/`company_id`. Admins can create a
  `role="manager"` account tied to a company directly via `POST /profile/create-manager`.
- **Talent**: `groups`, `idols`, `idol_colors`, `positions`/`idol_positions` — full ORM + schema +
  service + router, company-scoped CRUD.
- **Events & ticketing**: `venues`, `concerts`/`concert_performers`, `ticket_types`,
  `lottery_preferences`, `lottery_campaigns`, `lottery_entries`, `tickets` — full ORM + schema +
  service + router. `tickets` creation is admin-only (a manual stopgap — see §4).
- **Marketplace**: `categories.is_resale_capped`, `album_details`, `genres`/`album_genres`,
  `merch_details` — full ORM + schema + service + router.
- **Image uploads**: `idols.profile_image_url` / `products.image_url`, a local/S3 storage
  abstraction (`app/utils/storage.py`), inline upload on creation plus a dedicated
  `POST /{domain}/{id}/image` to replace one later. Full detail: `database-design.md` §9.
- **Seed data** (`scripts/seed.py`): idempotent — 3 management companies, 8 users, 25 idols across
  5 groups + 3 solos, 6 venues, 6 concerts, 18 ticket types (lottery + direct sale), 5 categories,
  a 20-item marketplace, 2 lottery campaigns with preferences/entries, 1 manually-issued ticket.
  Idol portraits and product covers are procedural placeholder art pushed through the real
  `get_storage().save()` pipeline — see `tests/fixtures/README.md`.
- **Notifications** (`app/db/models/shared/notification.py`): a `notifications` table
  (`database-design.md` §3.19) covering 12 event types, one nullable FK per referenced entity kind.
  Producers fire inline (no cron/Beat job): `order_service.checkout()`,
  `ticket_service.checkout_ticket()`/`checkout_won_ticket()`, `user_service.verify_rtoken()`,
  `lottery_draw_service.draw_lottery()` (`lottery_result` for every winner and loser, plus a
  payment reminder for winners, fired at draw time rather than on a schedule closer to the
  deadline; also calls `concert_service.notify_managers_of_draw_completion()` for
  `lottery_draw_completed` right after its own commit lands — every manager at the concert's
  company, not just whoever triggered it),
  `lottery_entry_service._stage_entry()` (`lottery_registered`, fired the moment a fan's entry is
  staged — shared by the single and batch apply endpoints, same commit as the entry itself),
  `concert_service.notify_managers_of_draw_trigger()` (`lottery_draw_triggered`, fired from the
  `PUT /concerts/lottery-draw/{id}` router the moment a manager/admin presses draw — every manager
  at the concert's own company gets one, not just whoever clicked, since the draw itself is
  fire-and-forget onto a Celery worker and this is the only record any of them get that one is now
  in flight), `concert_service.notify_managers_of_draw_failure()` (`lottery_draw_failed`,
  called from `draw_lottery_task`'s own `except Exception` block in `app/tasks/lottery.py` —
  rolls back, notifies the same audience as the trigger notification, then re-raises the original
  exception so the task still surfaces as a Celery `FAILURE` rather than silently looking like a
  success; see §8's updated Notifications note), and `order_service.ship_order()`
  (`order_shipped`, fired from `PATCH /order/{order_id}/ship` — the manager-facing "Ship" button,
  §4 item 43 — to the order's own buyer, same commit as the status flip to `"shipped"`). Every
  write lands in the same commit as the event it describes. Fan-facing API:
  `GET /notifications/mine`, `GET /notifications/unread-count` (polled, no WebSocket/SSE layer),
  `POST /notifications/{id}/read`, `POST /notifications/read-all` — self-scoped, rate-limited.
  `event_reminder` still has no producer. `notifications.status`/`sent_at`
  sit at `pending`/`null` forever regardless — that pair tracks a push-to-inbox step this table
  itself doesn't drive (see Email dispatch below, a separate path).
- **Email dispatch**: every transactional email — verification link, order placed, ticket
  confirmed, lottery ticket payment confirmed — goes through
  `celery_app.send_task("app.tasks.email.send_email", ...)`, picked up by the worker task in
  `app/tasks/email.py`, which calls `app/utils/email_sender.py`'s Resend wrapper. Subject/body
  text for each lives in `app/utils/email_templates.py`'s `EmailTemplate` enum (`.subject`,
  `.render(**fields)`) rather than inline at each call site. Replaces the original
  `BackgroundTasks.add_task` approach (verification email only) — that wouldn't have worked from
  a Celery task's own worker process (no request-scoped `BackgroundTasks` to hang a send off of),
  which mattered when `draw_lottery` still sent win/loss email itself; it no longer does (see
  below), but the rest of the app kept the Celery-based dispatch for consistency rather than
  reverting. This is independent of the in-app `notifications` table above: both fire off the same
  triggering events, but one doesn't feed the other. **`draw_lottery` deliberately sends no email
  at all** — win and loss are in-app `lottery_result` notifications only (§8), a scope change made
  so testing the lottery flow against real seed-fan email addresses doesn't spam real inboxes on
  every draw; `LOTTERY_WON`/`LOTTERY_LOST` were removed from `EmailTemplate` since nothing
  references them anymore.
- **Celery skeleton** (`app/celery_app.py`, `app/tasks/`): broker + result backend on the same
  Redis instance, a separate DB index from the cache/rate-limiter. Two task modules:
  `app.tasks.lottery.draw_lottery` (manager-triggered, §8) and `app.tasks.email.send_email` (every
  email dispatch above). No Celery Beat / scheduler is used or planned for this phase — every
  producer fires inline; a periodic job (payment-deadline reminders, an ETL sweep) stays open, see
  §5.
- **12 DB triggers / 8 trigger functions** enforcing the money/fairness invariants
  `database-design.md` §4 lists (fan-only purchasing, the anti-resale cap, concert
  ticket-capacity, the lottery entry cap, the preference-required check, the lottery
  preference/concert match, the album/merch mutual-exclusivity pair).

## 3. Verification method (and its limit)

~~Most of this project has been built without a reachable live Postgres/network connection~~ —
**DONE**: the app is deployed to Render (API) with Supabase as the Postgres backend.
`alembic upgrade head` runs clean against the real Supabase instance, the deployed app is live and
reachable, and real endpoints have been exercised against it end to end — the PayPal Sandbox
checkout in §7, confirmed both locally and against this same deployed Render app, is one specific
example. The full `pytest` suite itself still runs locally against a disposable Postgres
(`tests/integration/conftest.py`), not against the deployed Supabase database — that's a separate
exercise from "the deployed app works end to end," not claimed here.

Day-to-day local development still happens without a reachable live Postgres for most changes, so
those are verified with:

1. A full `py_compile` sweep across `app/`, `main.py`, and `alembic/`.
2. An AST-based scan of every ORM model's `ForeignKey` targets and
   `relationship(back_populates=...)` pairs, confirming every FK and relationship pair resolves.
3. An AST-based scan of every intra-app `from app.X import Y` statement, confirming the imported
   name exists in its target module.

Neither exercises real SQL or a running app — a substitute for the deployment-level verification
above, not a replacement for it, for whatever a given change hasn't separately exercised there.
Locally, where a live Postgres/Redis has been reachable, verification has also gone further: a
full `pip install` + `import main` end to end, `pytest tests/unit` against real imports (not just
syntax), and for the notifications feature specifically, a full `alembic upgrade head` from empty
plus driving the feature over real HTTP (register → request a password reset → complete it →
confirm the notification through `/notifications/mine`, `/unread-count`, and `/read`) and
confirming the rate limiter under load (429s past budget). That run: 339/339 tests passed, no
regressions.

**Integration tests used to run directly against the shared dev database** — the same one
`app`/`worker`/`scripts/seed.py` use. Several tests asserted a table returns `404`/empty with zero
rows, which was only ever true against a genuinely empty database; any real seeded data made them
fail. Fixed at the root: `tests/conftest.py` now redirects `DATABASE_URL` onto a dedicated
`<name>_test` database before anything else imports `app.config.settings`, and
`tests/integration/conftest.py` drops, recreates, and fully migrates that database once per test
session. `pytest tests` is now deterministic regardless of dev-DB state and never touches real
data. `pytest tests/unit` needs no live Postgres at all — the redirect is a pure string rewrite.

**Unit coverage pass (`pytest --cov=app`, 46% → substantially higher, 213 → 393 unit tests)**:
filled in every events-domain service that had zero unit coverage (`ticket_type_service`,
`lottery_campaign_service`, `direct_sale_campaign_service`, `lottery_entry_service`,
`lottery_preference_service`, `concert_service`, `venue_service`), added `test_cache_service.py`
(previously untested despite `CacheService` being the whole caching layer — its tests run against
`tests/conftest.py`'s session-wide `fake_redis`, not a per-test mock, so a cache hit genuinely
skips the wrapped service call and a delete genuinely clears the key), added
`test_notification_service.py`, and filled in missing branches in the existing
`product_service`/`payment_service`/`shipping_service`/`user_service` test files (`get_product_detail`'s
recommendation logic, `finalize_paypal_payment`'s ticket/order branches, `verify_rtoken`, etc.).

**Deliberately not covered here**: `ticket_service.checkout_ticket`/`checkout_won_ticket` and
`order_service.checkout` — the `with_for_update()` pessimistic-locking paths behind item 1's
overselling-race fix. `lottery_draw_service`, which uses the same locking pattern, already has its
own dedicated test file; these two don't. Left out on purpose rather than gold-plated in a pass
that was otherwise routine CRUD/RBAC coverage — see §5.

## 4. Known issues / tech debt (fix alongside the surrounding code, not standalone)

Ordered roughly by how much each matters to the idol-ticket domain specifically. Items marked
FIXED were pre-existing bugs in the forked boilerplate, closed during this project — not
newly introduced.

1. ~~**Checkout is not one atomic transaction, and has a stock-overselling race**~~ — **FIXED**.
   `order_service.checkout()` checks the cart total and resale cap, takes one
   `ORDER BY Product.id ... with_for_update()` lock across every needed `Product` row
   (UUID-ordered, deadlock-safe), holds it through the `Order`/`OrderItem` inserts and
   `create_payment()` (non-committing), and commits once via `commit_or_raise()` — mirroring
   `ticket_service.checkout_ticket()`'s lock-hold-commit-once pattern for `ticket_type`/`sold_quantity`.
   Still open: the draw job (§8) needs the same guard designed in from the start.

   **Regression found and fixed**: the lock above was real but silently ineffective for any
   product in a resale-capped category (`categories.is_resale_capped` defaults `true()` at the DB
   level — category.py:16 — so this was the common case, not an edge case). The resale-cap
   pre-check a few lines earlier (`capped_products = db.query(Product).filter(...).all()`) reads
   the same `Product` rows into the session's identity map *before* the real stock-check query's
   `with_for_update()` runs. Postgres still took the row lock correctly, but SQLAlchemy returned
   the stale pre-lock Python object instead of the freshly-locked row, so `product.quantity <
   item.quantity` ran on stale data. Confirmed directly: racing 3 concurrent checkouts against
   `quantity=1` on a capped category let all 3 "succeed," with final stock landing at `0` rather
   than `-2` — a classic lost update, each thread reading the same stale `quantity=1` and each
   independently writing `0`. Fixed by adding `.populate_existing()` to the `with_for_update()`
   query, which forces SQLAlchemy to overwrite the identity-map copy with the freshly locked row.
   Found and confirmed via the new concurrency tests below, not by inspection — the lock read
   correctly on paper, so this needed real concurrent transactions against a real Postgres to
   surface at all.

   **Verification**: `tests/integration/marketplace/test_orders_concurrency.py` (two tests: an
   oversell guard racing 3 checkouts against 1 unit of stock, and an exact-stock variant racing N
   checkouts against N units to confirm the lock doesn't over-serialize either) and
   `tests/integration/events/test_lottery_concurrency.py` (races 2 concurrent
   `LotteryDrawService.draw_lottery` calls for the same concert, confirming the same
   `with_for_update()` pattern there — item 8 below — actually serializes). Both use a shared
   `tests/integration/_concurrency.py` harness (`threading.Barrier`-synchronized racer threads
   against the real dockerized test Postgres, not mocked). Full suite reconfirmed clean after the
   fix: 393/393 unit, 235/235 integration (232 pre-existing + these 3 new).
2. ~~**The rate limiter's key doesn't include the route**~~ — **FIXED**. `ip_key`/`user_key`
   now fold `request.scope["route"].path` into the Redis key (`rate:ip:<route>:<ip>`), so
   endpoints sharing a `key_func` no longer share one counter.
   ~~**`ip_key` had no `X-Forwarded-For`/`X-Real-IP` handling**~~ — **FIXED**. Behind Render's
   reverse proxy, `request.client.host` was Render's own edge IP for every visitor. Fixed at the
   transport layer with `uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware`
   (`trusted_hosts="*"`, since only Render's network can reach the container directly), not a
   hand-rolled `X-Forwarded-For` parse — that header is client-settable, so a naive parse would
   let an attacker mint a fresh bucket per request.
   ~~**Two more real bugs**~~ — **FIXED**: (a) the limiter's `GET` → conditional `SETEX`/`INCR`
   sequence was a non-atomic check-then-act, so a burst of concurrent requests could all see "no
   counter yet" and never trip the limit. Replaced with one atomic `INCR` plus `EXPIRE` set only
   by the request that created the window. (b) no error handling around the Redis calls — an
   outage 500'd every rate-limited route, including login. Now wrapped in
   `try/except redis.RedisError`, fail-open (lets the request through) rather than fail-closed,
   since availability matters more than enforcement during an outage. Covered by
   `tests/unit/test_rate_limit.py` (a sequential limit test, and a threaded-concurrency test
   firing 50 requests at a `limit=10` bucket). `user_key` still implicitly depends on
   `get_current_user` running first to populate `request.state.user` — an unenforced ordering
   that holds by convention, not a bug in itself.

   **Considered, not built: a Lua/`EVAL` version.** The atomic `INCR` + conditional `EXPIRE`
   above is still two round-trips — a crash between them leaves a key that never expires. A Lua
   script would close this (Redis runs it as one indivisible unit), but `fakeredis` doesn't
   support `EVAL` without an extra dependency this project doesn't otherwise need. A documented,
   accepted residual risk, not an oversight.
3. ~~`app/db/base.py` didn't import every model~~ — **FIXED**. `Base` now lives in
   `app/db/base_class.py`; `app/db/base.py` is a pure aggregator. See `architecture.md` §5.
4. ~~**Webhook handling isn't idempotent**~~ — **FIXED**, once PayPal was actually integrated
   (§7). `finalize_paypal_payment` only does real work when `payment.status == pending`, so a
   duplicate or out-of-order webhook delivery is a no-op rather than a double-fulfillment — see
   §7 for why no separate event-id ledger was needed.
5. ~~**Minor schema type inconsistencies**: `OrderItem.price` is `Integer` while `Product.price` is
   `Float` (truncates fractional prices in order history); `ShippingAddress.postal_code` is
   `Integer`, which breaks for alphanumeric postal codes (UK, Canada, Japan)~~ — **FIXED**. Two
   migrations (`54347349d0f2`, `bfadb696c92a`): `orders_items.price` → `Float`,
   `shipping_addresses.postal_code` → `String`. Both widen an existing column, so no backfill is
   needed; the matching Pydantic schemas (`OrderItem`, `ManagerOrderItemRead`, `ProductSaleRead`,
   `ShippingBase`) were updated to match so the type fix doesn't get silently undone by
   `response_model=`/request-body coercion at the HTTP boundary.
6. ~~**CORS `allow_origins` is hardcoded**~~ — **FIXED**. `main.py` builds `origins` from a
   `CORS_ORIGINS` setting (comma-separated, default `http://localhost:8080`) — see
   `docs/deployment.md`.
7. ~~**`cart_service.add_to_cart` doesn't lock the `Product` row**~~ — **FIXED**. The stock check
   now runs against a `with_for_update()`-locked row, same as the `Cart`-row lookup beside it.
   Checkout's own lock (item 1) was already the real money-safety gate — `add_to_cart` never
   decrements `product.quantity` — but without this lock a concurrent cart-add could read a
   pre-decrement quantity mid-checkout, a stale-read issue rather than an overselling one.
8. ~~**The draw job needs its own concurrency guard**~~ — **FIXED**; see §8.
9. ~~**Trigger errors have nowhere clean to land.**~~ — **FIXED**. `app/exception/db_triggers.py`
   adds `TriggerViolationError` + 8 typed subclasses, a `translate_trigger_error()` that matches
   a caught `DBAPIError`'s Postgres message against each trigger's known wording, and
   `commit_or_raise()`/`flush_or_raise()` replacing a bare `db.commit()`/`db.flush()` at any write
   a trigger can fire on. Wired into the service functions that reach a trigger-covered
   insert/update and their routers, each catching `TriggerViolationError` and mapping it via
   `e.status_code` (403 for the fan-only-purchase trigger, 400 for the rest). Follows the same
   raise-in-service/catch-in-router shape as `app/exception/checkout.py` — see `architecture.md`
   §2.
10. ~~`products`/`categories` still lack company-scoping~~ — **FIXED for `products`**;
    `categories` never needed it, since every category-mutating endpoint is already
    `require_admin`-only. A product has no `company_id` column, so
    `product_service._resolve_product_company_id()` resolves ownership through whichever of
    `album_details`/`merch_details` references it, then that row's `idol_id`/`group_id`.
    `update_product`, `set_product_image`, and `delete_product` now check this and raise
    `ForbiddenError` for a manager outside their company. A product tied to neither table (plain
    merch) resolves to no owner and stays manager-agnostic — a deliberate state, not a gap.
    `add_product`/`add_bulk_products` stay unscoped, since a bare `Product` has no idol/group link
    yet at creation.
11. ~~**Stale unit/integration tests drifted from production code**~~ — **FIXED**. Several tests
    across `TestProductService`, `TestCategoryService`, `TestCartService`, `TestUserService`, and
    `TestPaymentService` had drifted from already-correct service code — a required parameter
    added under item 10's scoping fix, a schema swapped for the wrong `*Update` class, a mock
    chain that didn't account for a new `with_for_update()` hop, an assertion contradicting the
    documented anti-enumeration behavior (§4 item 18), and a missing required `idempotency_key`
    field (item 16). All were test bugs, not app bugs — every failure was the suite lagging behind
    landed service changes, fixed by updating the tests to match.
12. ~~**Seeded accounts share a hardcoded, publicly-committed password**~~ — **FIXED**.
    `scripts/seed.py` creates an admin, three managers, and twelve fans all with the same password
    — now `SEED_PASSWORD` read from the environment (`os.environ.get("SEED_PASSWORD", ...)`), with
    the old hardcoded string kept only as the local-dev fallback default. `.env.example` documents
    the var (commented out, since it's optional and dev-only). Still on the deployer to actually set
    it before ever running this script against a real database — this fixes the "committed to the
    repo, silently the same everywhere" problem, not the "don't seed a real deployment with
    guessable accounts at all" one, which is a separate judgment call for whoever deploys.
13. ~~**An invalid `category_id` on a product write crashed with a raw 500**~~ — **FIXED**.
    `add_product`/`update_product`/`add_bulk_products` set `category_id` with no existence check,
    so a bad id raised an uncaught `IntegrityError` at commit instead of a 4xx. `update_product`
    now raises `NotFoundError`; `add_bulk_products` checks every referenced category up front,
    all-or-nothing.
14. ~~**Plain "Merch" products have no company ownership at all**~~ — **FIXED**. A manager could
    edit/delete a merch item whose *name* signalled which company it belonged to, with no
    structural link enforcing it — `_resolve_product_company_id` had nothing to resolve merch
    ownership against. Fixed by merging the `Lightstick` category into `Merch` and generalizing
    `lightstick_details` into `merch_details`, rather than building a second near-identical detail
    table — nothing in the business rules ever actually distinguished a lightstick from any other
    piece of official branded merch. Full reasoning: `database-design.md` §3.15/§3.17.
15. ~~**`DELETE /profile/delete` 500'd for any user with a `shipping_addresses` row**~~ —
    **FIXED**. `Users`' relationships to `shipping_addresses`/`cart`/`orders`/`payment` had no
    `passive_deletes`, so SQLAlchemy tried to nullify each child's `user_id` before the parent
    delete — which violated their `NOT NULL` constraints even though the FKs already declare
    `ON DELETE CASCADE` at the DB level. Fixed by adding `passive_deletes=True` to all four, so
    SQLAlchemy lets Postgres's own cascade handle it.
16. ~~**No client-retry idempotency on either checkout endpoint**~~ — **FIXED**.
    `payment.idempotency_key` is a `UUID NOT NULL UNIQUE` column; `PaymentCreate`/
    `TicketCheckoutCreate` both require it, and checkout checks for a matching key before doing
    anything else, raising `DuplicateIdempotencyKeyError` rather than creating a second `Payment`
    row. A double-click or retry now gets a clean rejection instead of a duplicate charge.
17. ~~**`delete_group`/`delete_idol` hard-deleted the row**~~ — **FIXED**. Both are FK targets
    with real cascade behavior — a hard delete would wipe concert-performer history
    (`ondelete="CASCADE"`) or orphan product artist attribution (`ondelete="SET NULL"`). Both
    services now soft-delete via `is_active`, with matching `reactivate_group`/`reactivate_idol`
    endpoints. Store-facing reads filter to `is_active=True`; manager/admin reads and by-id
    lookups don't, so an edit form can still load a deactivated row to reactivate it. Deactivating
    a group doesn't cascade to its idols; a deactivated idol/group is closed to *new* attachments
    (assigning an idol into it, attaching a new release) but existing ones are untouched.
    Reactivation is a dedicated `PATCH .../activate/{id}`, not a field on the general `PUT
    /update`, since neither `Update` schema is a partial body.
18. ~~**Verification/reset tokens had no dev-visible surface**~~ — **FIXED**. `SENDGRID_API_KEY`
    is a placeholder in local dev, so verification/reset emails always failed to send, and the
    token inside had nowhere visible to land since the send happens off the request/response cycle
    (originally a `BackgroundTasks` call, now a Celery task — item 27). `settings.DEBUG=true` now
    prints the full email body — token included — to the console before attempting the real
    SendGrid call. Deliberately not solved by returning the token in the API response:
    `forgot-password` is intentionally anti-enumeration (identical response whether or not the
    email is registered), and a real token in the response would reopen that side channel. `DEBUG`
    must stay `false` in production.

19. ~~**A fan could hold both a direct-sale ticket and an active lottery claim on the same
    concert**~~ — **FIXED**. `lottery_entry_service.apply_to_lottery` didn't check for an existing
    live ticket before letting a fan apply to another tier's lottery — now raises `BadRequestError`
    if one exists. `ticket_service.checkout_ticket` didn't check lottery standing before a direct
    purchase — now raises `LotteryEntryUnresolvedError` if any lottery entry for that concert is
    still `pending` or `won`. The `won`-without-a-live-ticket case (a fan who won but let the
    payment deadline lapse) is the gap `trg_tickets_one_per_concert` alone can't catch. Verified
    with 4 new integration tests against real fixture rows.
20. ~~**`pytest tests` ran integration tests directly against the shared dev database**~~ —
    **FIXED**. See §3 for the full fix. This was the actual root cause of a dozen tests that
    asserted "empty table" behavior only true against a genuinely empty database — one shared bug,
    not a dozen separate ones.
21. ~~**The product-list cache goes stale after every purchase**~~ — **FIXED**. Neither
    `order_service.checkout()` nor `payment_service.finalize_paypal_payment()` invalidated the
    product cache on a successful purchase, despite both decrementing `Product.quantity`. Both now
    call `delete_cached_products()` right after their commit, gated on the same success condition
    that gates the quantity write. `get_cached_products` still hand-rolls a subset of `ProductRead`
    as a raw dict rather than reusing the schema — a schema change won't propagate to the cached
    path; not addressed here. `get_store_page_data` was added to caching in the same pass, built by
    dumping the real `StorePageRead` model instead of a second hand-rolled dict.
    `paginated_product`/`filter_product` stay uncached — `filter_product`'s key space is unbounded
    and client-controlled, so caching it would mean paying for writes that rarely get read back and
    handing an unauthenticated caller a way to fill Redis with junk keys.
22. ~~**Almost no function had a return type, and ~3% of parameters had none**~~ — **FIXED**.
    406 real findings across `app/router` and `app/services`, enforced going forward via ruff's
    `ANN` rules — `tests/*`/`scripts/*` exempted. Sentinel-return functions got precise
    `Literal["forbidden", "not_found"]` unions instead of a loose `str`. Caught two real bugs while
    writing the annotations (a stray-argument `TypeError`, a list-where-instance-expected
    `ValidationError`) and a FastAPI gotcha — a route's own return-type annotation becomes an
    implicit `response_model` when the decorator has none, so a bare ORM class there crashes the
    app at import time; fixed with `response_model=None` where needed. Full reasoning:
    `docs/architecture.md` §5.
23. ~~**Two error-handling conventions coexisted: string sentinels for most RBAC/company-scoping
    failures, real exceptions for checkout/payment and DB-trigger violations**~~ — **FIXED,
    unified on exceptions**. All 14 router+service pairs using the old `_raise_for`/
    `_raise_for_link` sentinel pattern now raise `NotFoundError`/`ForbiddenError`/`BadRequestError`
    (`app/exception/common.py`) — see `docs/architecture.md` §2. Each raise site got a more
    specific message than the single blanket string the old pattern covered every failure reason
    with. `idol_service._validate_refs` and its siblings deliberately keep the sentinel-return
    shape, since a caller needs to inspect/override the result before deciding it's an error.
    Every delete/unassign function in this group now returns the deleted/unlinked ORM object
    itself instead of `Literal[True]`, for callers that want the actual row.
24. ~~**Every `{"msg": "..."}` router return was a bare `dict[str, str]`, invisible to OpenAPI as
    a documented schema**~~ — **FIXED**. Added `app/schema/common.py::MessageResponse` and
    switched every such endpoint (40 across 22 router files) to `response_model=MessageResponse`.
    `/account/login`/`/account/refresh`/`/profile/logout` stay on a raw `JSONResponse` (cookie
    handling, or an extra field alongside `msg`). One real, frontend-visible change:
    `products.py::delete_existing_product` used `{"detail": ...}` instead of `{"msg": ...}` — now
    matches every sibling endpoint, so a client reading `response.detail` there needs to switch to
    `response.msg`.
25. ~~**Four more router functions returned a raw `dict` with no `response_model`**~~ — **FIXED**.
    `cart.py::check_cart`, `products.py::search_existing_product`/`paginated_product`/
    `filter_product` now declare a real `response_model` (`CartDetailRead`, `ProductWithCategoryRead`,
    `ProductsPageRead`). `ProductWithCategoryRead` is a new schema, not a `ProductRead` change —
    `ProductRead.category` is a resolved name (`str`); these three functions return raw `Product`
    rows with the `Category` relationship still attached, so embedding `CategoryRead` directly is
    correct for them. `POST /cart/add_cart` has the same underlying gap (opts out via
    `response_model=None`, returns a raw `Cart` object) but wasn't touched here.
26. ~~**Every remaining service function typed `-> dict[str, Any]` built and returned a plain
    dict, relying on `response_model=` to shape it into a schema at the HTTP boundary**~~ —
    **FIXED**. 21 functions across 7 service files now construct and return the real schema
    instance — every one already had a matching schema and `response_model=` at the router.
    `product_service._build_product_cards` returning `list[ProductCard]` instead of `list[dict]`
    had a ripple effect: callers reading a card by dict key (`get_product_detail`'s recommendation
    logic, `group_service.get_group_detail`'s artist filter) switched to attribute access.
    `ProductCard` intentionally has no `from_attributes` config — it's always hand-constructed from
    already-resolved values, never validated off a raw ORM row. This also surfaced a unit-test
    gotcha: `MagicMock` auto-vivifies any attribute access, which defeats a `from_attributes`
    schema's "missing attribute → use the default" fallback — a mock that never explicitly set
    `debut_date`/`created_at`/etc. passed silently before, then failed validation once the service
    started constructing the real schema. Fixed by making the shared mock factories set every field
    their target schemas need.
27. **Email dispatch moved from `BackgroundTasks` to Celery, and extended past verification-only**.
    `email_verification_process` used to fire via `BackgroundTasks.add_task` — fine for a
    request-scoped flow, but `lottery_draw_service.draw_lottery` is itself a Celery task with no
    request to hang a `BackgroundTasks` off of, so its win/loss/payment-reminder notifications
    never had a matching email. Every email send (verification, order placed, ticket confirmed,
    lottery win, lottery loss, lottery ticket payment confirmed) now goes through one
    `app.tasks.email.send_email` Celery task, dispatched via `celery_app.send_task(...)` at each
    call site. Subject/body text moved out of inline f-strings into
    `app/utils/email_templates.py`'s `EmailTemplate` enum, one member per email, with `.subject`
    and `.render(**fields)`. Caught two real bugs while wiring this up: the task function in
    `app/tasks/email.py` was named the same as the `send_email` helper it called, so it shadowed
    its own import and recursed into itself instead of ever sending anything; and
    `app/celery_app.py`'s `include` list never listed the new `app.tasks.email` module, so a worker
    would never discover the task at all.
28. **Extended Redis caching past the product list to every other unauthenticated, unpersonalized
    page-shaped read**: `GET /concerts/events-page`, `GET /idols/members-page`,
    `GET /groups/groups-page`, `GET /venues/all`, `GET /idol_colors/all`. Same shape as the
    existing product cache (`app/cache/cache_service.py`): msgpack-serialized, 5-minute TTL
    (`_TTL_SECONDS`), invalidated on every add/update/delete/reactivate that can change the cached
    page, called from the router right after the mutating service call succeeds — not from inside
    the service, since `cache_service.py` already imports these services for the read side, and a
    service importing back would be a circular import. `groups-page`'s `member_count` and
    `members-page`'s active-groups filter each depend on the *other* domain's rows, so an idol
    add/update/delete/reactivate invalidates both caches, and so does a group
    add/update/delete/reactivate. Venue/idol-color edits do **not** invalidate `events-page`'s
    embedded `VenueRead`/an idol's embedded color hex — accepted staleness (up to 5 minutes) on
    cosmetic, non-money fields, same trade-off the product cache already made and documented in
    item 21, not chased further here.
29. **Extended the same caching to every manager/admin settings page**: `GET
    /idols/manager-idols-page`, `GET /idols/manager-idol-form-page`, `GET
    /groups/manager-groups-page`, `GET /concerts/manager-events-page`, `GET
    /products/manager-products-page`, `GET /products/manager-product-form-page`, `GET
    /management_companies/all`. Same TTL+invalidate-on-write shape as item 28; these never 404 on
    an empty result (a brand-new company's empty product list is a normal state), so there's no
    `None` branch to cache around, unlike the store-facing pages. The two products pages
    are the only ones keyed by `company_id` (`products:manager_products_page:<company_id|"all">`)
    since they're the only ones scoped — a manager's cached page must never leak into another
    company's, or into the admin's unfiltered view. Their `company_id` isn't a column on `Product`
    itself (resolved indirectly through `album_details`/`merch_details`), so invalidation clears
    every company's key via `redis_client.keys(...)` rather than computing which one a given write
    actually touched — an O(N) scan, fine at this project's key count, not something a
    high-traffic deployment would want unchanged. Idol/group/idol-color mutations cross-invalidate
    into whichever manager pages embed their rows (the idol/group form dropdowns, the color
    picker), same reasoning as item 28's members/groups cross-invalidation. **Separately noticed,
    not fixed here**: none of these seven manager/admin GET endpoints actually check
    `require_manager_or_admin`/`require_admin` — no auth dependency at all, unlike every mutating
    endpoint on the same resources. Caching makes an unauthenticated read of this data cheaper,
    not more exposed than it already was; flagging so it doesn't get missed as this list is
    extended further.
30. ~~**`POST /order/checkout` emailed "your order has been placed" even on a declined mock
    payment**~~ — **FIXED**. `OrderService.checkout` correctly gates the in-app
    `order_confirmation` notification on `payment.status == PaymentStatus.success`, but the
    router's `EmailTemplate.ORDER_PLACED` dispatch had no such gate — it fired on any non-exception
    return, and a decline (`simulate_succ=false`) doesn't raise, it just sets `order.status =
    cancelled` and returns normally. Found while writing up the checkout flow for the monolith
    README; fixed by skipping the email when `order.status == OrderStatus.cancelled`. The
    equivalent ticket path (`ticket_service.checkout_ticket`) never had this bug — its email
    dispatch already lives inside the same `if payment.status == PaymentStatus.success:` block as
    the notification, in the service rather than the router.
31. **Extended the same caching to the idol/group detail pages**: `GET /idols/{id}/detail`,
    `GET /groups/{id}/detail`. Same TTL+invalidate-on-write shape as items 28/29, but per-id keyed
    (`idols:detail:<id>`, `groups:detail:<id>`) rather than one shared key, since each id is its own
    cache entry. An idol's detail page embeds its group and its siblings (other idols sharing its
    `group_id`); a group's detail page embeds every member's idol data — so a write to either side
    can invalidate detail pages keyed by ids the write has no direct handle on (renaming a group
    must bust the cache of idols the update endpoint never sees an id for). Rather than resolve
    which ids share a `group_id` before every write, `CacheService.delete_cached_idol_details`/
    `CacheService.delete_cached_group_details` each clear their whole namespace via
    `redis_client.keys(...)`, same O(N)-scan tradeoff as item 29's manager-products invalidation —
    called together from every idol and group mutation (add/update/delete/reactivate/image-upload),
    since either side's write can affect both caches.
32. **Converted `cache_service.py` from a flat module of functions to `class CacheService` (all
    `@staticmethod`s)**, matching the router/service-layer convention documented in
    `architecture.md` §2 item 2 — every caller across 9 files now imports `CacheService` and calls
    `CacheService.get_cached_x(...)`/`CacheService.delete_cached_x(...)` instead of importing each
    function by name. While sweeping for leftover direct `redis_client` calls outside
    `cache_service.py`, found two in `products.py` (`add_new_product`, `add_new_product_with_detail`)
    that called `redis_client.delete("products:list")` directly instead of going through
    `CacheService.delete_cached_products()` — which also clears `products:store_page`. Both spots
    only cleared the `/products/all` cache, so a product added through either endpoint left the
    store page's cached product list stale for up to 5 minutes; now fixed as a side effect of
    routing both through `CacheService`. `rate_limit.py`'s direct `redis_client.incr`/`expire`/`ttl`
    calls were deliberately left alone — fixed-window rate limiting is a different concern from
    page caching and has no `CacheService` equivalent to route through.
33. **Cached `GET /products/{id}/detail` and `GET /concerts/{id}/detail`**, both reported by the
    frontend as hot paths (`ProductDetailPage.vue`/`EventDetailPage.vue`). The product one is a
    straight extension of item 31's shape: `products:<id>:detail`, invalidated (namespace-wide,
    same fan-out reasoning as idol/group details — recommendations pull from every other product)
    from every product mutation endpoint.

    The concert one is not that simple: `ConcertDetailRead` bundles `has_ticket`/
    `has_won_lottery`/`entered_campaign_ids`/`my_lottery_preferences` alongside the public
    concert/venue/ticket-types/lineup/campaigns data, and those four fields are per-viewer —
    caching the response verbatim would let one fan's cache hit leak another fan's ticket/lottery
    state. Fixed by splitting `concert_service.get_concert_detail` (removed) into
    `get_concert_detail_public` (concert/venue/ticket_types/lineup/performing_groups/campaigns
    only, personalized fields left at their False/empty schema defaults — this is the part
    `CacheService.get_cached_concert_detail` caches under `concerts:<id>:detail`) and
    `get_personalization` (the four per-viewer fields, computed fresh on every request, never
    cached). `get_concert_detail_by_id` merges them with `result.model_copy(update=...)` only
    when a fan is logged in; a guest gets the cached bundle as-is. Chosen over the simpler
    alternative (skip the cache entirely for logged-in fans) because it keeps the cache-hit rate
    for logged-in traffic too, at the cost of one small uncached query per request for ticket/
    lottery state — same shape as `get_cached_store_page`.

    Unlike the idol/group namespace-wide invalidation, every write that can change a concert's
    cached bundle (the concert itself, one of its ticket types, a lottery/direct-sale campaign,
    a performer credit) already knows its own `concert_id` (or can resolve it via
    `TicketTypeService.get_ticket_type` for campaigns, which only have `ticket_type_id`), so
    `CacheService.delete_cached_concert_detail(concert_id)` is a precise single-key delete wired
    into `concert.py` (update/cancel/assign-performer/unassign-performer),
    `ticket_type.py` (add/update/delete), `lottery_campaign.py`, and `direct_sale_campaign.py`
    (add/update/delete on both).

    **Known, accepted gap, not fixed here**: `TicketType.sold_quantity` and a lottery campaign's
    `entry_count`/`status` change during ticket purchase (`ticket_service`, `payment_service`) and
    lottery draw (`lottery_draw_service`, run async in a Celery worker) — neither invalidates this
    cache, so a concert's displayed availability/entry-count can lag up to 5 minutes after a
    purchase or draw. Deliberately not chased into those flows here: unlike item 21's product-cache
    bug, this never risks overselling (the actual capacity check in `ticket_service`/
    `payment_service` reads live DB state, not the cache) — it's a display-only staleness, same
    category as item 28's accepted venue/idol-color staleness, just flagged explicitly since it
    touches ticket availability rather than a cosmetic field.
34. **Integration coverage pass**, run against a real Postgres+Redis (the pre-existing local
    `i-dolly-backend` Docker Compose project's `postgres`/`redis` containers, driven via the
    already-built `i-dolly-backend-app` image rather than a fresh env — every test in this item was
    actually executed, not just statically verified, which is the first time that's been possible
    for integration tests in a session without a live DB otherwise reachable, per §3). Added
    `tests/integration/identity/test_profile.py` (`/profile/me`, `/change-password`,
    `/forgot-password`, `/set-password`, `/logout`, `/make-admin`, `/create-manager`) and
    `test_account.py` (`/account/refresh`, `/verify-request`, `/verify`);
    `tests/integration/events/test_venues.py` (full `/venues` CRUD); `tests/integration/shared/
    test_notifications.py` (all four `/notifications/*` endpoints, seeded with a direct
    `type="password_reset"` row — the one notification type needing no order/ticket/lottery_entry/
    concert FK); `tests/integration/marketplace/test_payment.py` (`/payment/status/*`, plus
    `/payment/paypal/capture` and `/payment/paypal/webhook` with `create_order`/`capture_order`/
    `verify_webhook_signature` mocked — no real PayPal sandbox call). Extended
    `tests/integration/test_permissions.py` (reusing its existing `Factory`) with
    `/lottery_preferences/*`, `/lottery_entries/*` beyond `/apply`, and `/tickets/*` beyond
    `/checkout`.

    **Found and fixed along the way**: `UserService.promote_admin` (backing `/profile/make-admin`)
    only ever set the deprecated `is_admin` column, never `role` — but `require_admin` checks
    `role`, which `database-design.md`/`architecture.md` already document as the actual source of
    truth. So promoting a user through the only endpoint that does it left them just as unable to
    reach admin routes as before. Now sets both (still sets `is_admin` too, since that column isn't
    dropped yet). Caught by a regression test in `test_profile.py`
    (`test_make_admin_promotes_role_not_just_the_deprecated_flag`) that asserts the promoted user's
    *existing* access token gains admin access immediately, since `role` is read fresh from the DB
    per request rather than baked into the token. The two unit tests that exercised the old
    `is_admin`-only check (`test_user_service.py`) were updated to match.

    **Not covered here, still open**: group/idol CRUD *success* paths as an actual authenticated
    manager/admin (`test_permissions.py`'s `Factory` has no `group()` builder, and every existing
    group/idol test — in the domain-split `test_main` files — only reaches the 401/403/404 RBAC
    boundary, never a real 200). `/payment/status/order/{id}`'s found-case (needs a full
    product/cart/shipping-address chain behind a real `/order/checkout`, not built here — only its
    401/404 paths are covered). See §5 for both.
35. **`Object | Literal[False]` → `Object | None` across every plain-read service method**
    (~60 methods, 23 service files plus `cache_service.py`). `None` is Python's actual "nothing
    here" value and what `db.get(...)`/`.first()` already return on a miss, so a read wrapping one
    of those no longer needs a second falsy value meaning the same thing — see the updated
    convention note in `architecture.md` §2. Multi-value sentinels that happen to include `False`
    alongside other string outcomes (`product_service.update_product`'s
    `Literal[False, "forbidden", "price_locked", "category_not_found"]` and similar) were left
    alone on purpose — that's a different, still-valid pattern (`architecture.md` §2's "private
    multi-value helper" case), not the one this item touched. Every caller checking `if not
    result:` needed no change (`None` and `False` are both falsy); routers/tests using `is False`
    explicitly were updated to `is None`.

    **Found two real collisions along the way** — cases where `False` and `None` had already been
    doing two *different* jobs in the same function, which the rename would have silently merged
    into one, losing information callers relied on:
    - `OrderService.cancel_placed_order` returned `None` for "order not found" and `False` for
      "found, but already shipped" — `order.py`'s router turned these into 404 vs 400
      respectively. Fixed by raising `BadRequestError` for the "already shipped" case instead of
      returning a second falsy value, matching the exception-hierarchy convention item 199 of
      `architecture.md` already documents for this; the router now catches `ServiceError` for that
      endpoint.
    - `CartService.add_to_cart` returned `None` for "insufficient stock / product not found" and
      `False` for "user not found" (not reachable in practice — `user_id` always comes from an
      already-validated `get_current_user`, but the router still branched on it). Same fix:
      `NotFoundError` instead of a second falsy value.

    Neither collision was caught by a test — nothing exercised the "already shipped" 400 path or
    the (practically unreachable) "user not found" path, so a mechanical rename would have quietly
    turned both `HTTPException` branches into dead code without a single red test. Found instead by
    reading each router's own `is False`/`is None` branches during review, before running anything.
    Confirmed clean afterward: 393/393 unit, 232/232 integration (the latter against the real
    Postgres/Redis stack per item 34).

36. **Hardcoded value-set strings → `class X(str, Enum)` across identity/events/shared, matching
    the pattern `OrderStatus`/`PaymentStatus`/`ShippingStatus` already used in marketplace.** Before
    this, only marketplace had real Python enum classes backing its status columns; every other
    domain used a bare SQLAlchemy `Enum("a", "b", "c", name=...)` with no Python-side type, and
    service code compared against raw string literals scattered across call sites (`current_user.
    role == "manager"`, `ticket.status = "paid"`, `NotificationService.create_notification(db,
    user_id, "order_confirmation", ...)`, etc.) — a typo in any of them would have been a silent
    no-op or an `IntegrityError` at commit, not a caught-at-the-boundary validation error. New
    classes, one per model column, each living in the schema file that already owns that field's
    Read/Update model (see `architecture.md` §2): `UserRole` (`schema/identity/user.py`),
    `TicketTier`/`SaleMethod` (`schema/events/ticket_type.py`), `ConcertStatus`
    (`schema/events/concert.py`), `CampaignStatus` (`schema/events/lottery_campaign.py`),
    `DirectSaleCampaignStatus` (`schema/events/direct_sale_campaign.py`), `LotteryEntryStatus`
    (`schema/events/lottery_entry.py`), `TicketStatus` (`schema/events/ticket.py`),
    `NotificationStatus`/`NotificationType` (`schema/shared/notification.py`), and `ReleaseFormat`
    (`schema/marketplace/album_detail.py`). Every model `Column` now wires the matching class in
    (`Column(Enum(TicketStatus, name="ticket_status_enum"))`) instead of a bare inline value list;
    `server_default=` stays the plain string label since that's DDL text, not a Python default —
    no migration needed, the underlying Postgres enum types and labels are unchanged. Every
    comparison and assignment across the touched service/router files (~30 files: every
    `_manager_scope_violation` helper, `require_admin`/`require_manager_or_admin`, checkout/payment/
    lottery-draw status transitions, every `NotificationService.create_notification(...,
    notification_type=...)` call site) now uses the enum member instead of a raw string. Deliberately
    left alone: the sentinel-return strings the previous item's note already carves out (`Literal[
    "forbidden", "not_found"]` and similar multi-way function results — not a model column's value
    set) and every test file, since `str, Enum` members compare equal to plain strings and existing
    tests already mix literal strings with enum members for the fields that already had them
    (`OrderStatus`/`PaymentStatus`) — extending this to ~280 test-file occurrences across 22 files
    would have been pure churn with no behavior change. Confirmed clean: 393/393 unit, 232/232
    integration (real Postgres/Redis stack per item 34).

37. **Closed the remaining gap item 23 left open: six service methods that still returned a
    `Literal["forbidden", "not_found", ...]` sentinel instead of raising, because they didn't go
    through the old `_raise_for`/`_raise_for_link` router helper item 23's sweep was scoped to.**
    Converted to the same `NotFoundError`/`ForbiddenError`/`BadRequestError` hierarchy as everywhere
    else: `UserService.create_manager_user`, `ProductService.add_product_with_detail`/
    `update_product`/`set_product_image`/`delete_product`/`get_product_sales_page`, and
    `LotteryDrawService.draw_lottery` (called from `app/tasks/lottery.py`'s Celery task, not a
    router — an uncaught `ServiceError` there just fails the task, which is strictly more
    informative than the string sentinel nothing was reading before, since `PUT
    /concerts/lottery-draw/{id}` is fire-and-forget and never inspected the task's return value).
    `draw_lottery`'s return type was `-> dict` even though every early-return was a bare string
    that didn't match `dict` either — now `-> LotteryResult`, built as a real
    `LotteryResult(...)` instance on success instead of an untyped dict literal. Every router
    caller now does the one-line `except ServiceError as e: raise HTTPException(status_code=e.
    status_code, detail=str(e)) from e` instead of a chain of `if result == "...":` checks.
    One deliberate status-code change: `add_product_with_detail`'s `category_not_found`/
    `owner_not_found` (a bad FK reference in the POST body) moved from 400 to 404, matching how
    every other "referenced row doesn't exist" case in this codebase is already handled
    (`concert_service.add_concert`, `lottery_campaign_service.add_campaign`, etc. all raise
    `NotFoundError` for exactly this shape) — nothing tested the old 400, so this was a real
    inconsistency being fixed, not a documented contract being broken; `artist_inactive` stayed
    `BadRequestError`/400 (a state issue, not a missing reference) and `forbidden`/`price_locked`
    stayed `ForbiddenError`/403, both unchanged from before.

    Deliberately NOT touched: `idol_service._validate_refs` — still sentinel-returning, and still
    should be. It's a private helper whose callers (`add_idol`/`update_idol`) need to inspect and
    sometimes override its result (`update_idol` treats `"group_inactive"` as a non-error when the
    idol was already in that group before it got deactivated) before deciding it's an error, which
    an immediately-`raise`d exception can't express — `docs/architecture.md` §2 already documents
    this as the one legitimate exception to the "raise, don't return a sentinel" rule, not an
    oversight. Its sentinel values themselves were still a bare `Literal["company_not_found", ...]`
    though, so as a follow-up they're now a local `class _RefIssue(str, Enum)` next to the helper
    in `idol_service.py` — not `app/schema/`, since this isn't a model column's value set, just a
    private helper's own multi-way result compared against in two places (`add_idol`/`update_idol`).
    Same motivation as item 36's enum sweep (a typo in a member name is a caught `AttributeError`,
    not a string that silently never matches an `if error == "...":` branch) applied to the one
    sentinel-returning case item 36 didn't reach because it wasn't a `Column`. No behavior change —
    confirmed via the existing `add_idol`/`update_idol` tests, which already asserted on the public
    `NotFoundError`/`BadRequestError` raised around this helper, not on its internal return value:
    393/393 unit, 232/232 integration (real Postgres/Redis stack per item 34).

38. **Simplified ~33 genuine read methods that re-checked a result already known to be falsy or
    non-`None`, adding a branch that could never behave differently from just returning the query.**
    Two shapes:
    - A bare `list[X]`-returning read (`result = db.query(X)...all(); if not result: return None;
      return result`) collapsed to `return db.query(X)...all()`, typed `-> list[X]:` instead of
      `list[X] | None`. `.all()` already returns `[]`, never `None`, and `[]` is exactly as falsy as
      `None` was to the router's existing `if not result: raise HTTPException(404, ...)` — so this
      is a pure simplification, not a behavior change, for every router except one (below).
    - A single-object read that was only `db_x = db.get(X, id); if not db_x: return None; return
      db_x` (no other logic in between) collapsed to `return db.get(X, id)` directly. Stays typed
      `X | None` — unlike the list case, `.get()`/`.first()` genuinely can return `None`.
    26 files: `concert_service` (`get_concerts`/`get_performers`/`get_all_performers`),
    `idol_service.get_idols`, `group_service.get_groups`, `venue_service.get_venues`,
    `ticket_type_service.get_ticket_types`, `lottery_campaign_service.get_campaigns`,
    `direct_sale_campaign_service.get_campaigns`, `lottery_entry_service`
    (`get_my_entries`/`get_entries_for_campaign` — kept their existing `NotFoundError`/
    `ForbiddenError` pre-checks, only the final list return was simplified),
    `lottery_preference_service.get_my_preferences`, `management_company_service.get_companies`,
    `position_service` (`get_positions`/`get_idol_positions`/`get_all_idol_positions`),
    `idol_color_service.get_idol_colors`, `merch_detail_service.get_merch_details`,
    `album_detail_service.get_album_details`, `genre_service`
    (`get_genres`/`get_album_genres`/`get_all_album_genres`), `category_service.get_categories`,
    `product_service.list_of_products`, `payment_service`
    (`fetch_payment_status`/`fetch_ticket_payment_status`/`fetch_all_payments`),
    `order_service.fetch_single_placed_order` (and `get_user_shipping_status`, rewritten as a
    one-line ternary since it projects `.shippingstatus` off the queried row rather than returning
    the row itself), `shipping_service` (`fetch_address`/`get_address_by_id`),
    `notification_service.get_my_notifications`, `ticket_service.get_my_tickets`.

    **Deliberately NOT touched**: any read that wraps its query result in a bigger Pydantic object
    before returning (`get_events_page`, `get_members_page`, `get_group_detail`, `get_idol_detail`,
    `get_groups_page`, `get_concert_detail_public`, `get_store_page`, `get_product_detail`,
    `cart_service.see_cart`, `product_service.search_product`). A Pydantic model instance has no
    `__bool__`/`__len__` and is always truthy, so `if not entity: return None` in front of building
    one is the *only* way the router can tell "nothing here" from "found" — collapsing that check
    away would silently turn every empty result into a 200 with a half-built page instead of a 404.
    Same reasoning for `authenticate_user`/`verify_refresh_token` (real validation logic between the
    query and the return, not a redundant re-check) and the private helpers `idol_service.
    _validate_refs`/`ticket_service._existing_live_ticket`/`_unresolved_lottery_entry`.

    **Found one real bug while auditing router callers for the list-shape change**:
    `router/marketplace/payment.py::check_payment_status_all` checked `if payment is None:` against
    `fetch_all_payments`'s result — correct against the old `list[Payment] | None`, but silently
    wrong against the new `list[Payment]` (an empty list is never `None`, so a user with zero
    payments would have gotten a 200 with `[]` instead of the intended 404). Fixed to `if not
    payment:`, matching every sibling router's own check. Every other caller (routers and
    `CacheService`'s own wrappers around `list_of_products`/`get_venues`/`get_idol_colors`/
    `get_companies`) already used a falsy check, not an `is None` check, so needed no change.

    Test fallout: every `test_*_empty` unit test for a converted list-returning method asserted
    `result is None`; all ~27 switched to `result == []` (behavior at the HTTP boundary is
    identical — `[]` and `None` are both still falsy to the router's `if not result:`). Confirmed
    clean: 393/393 unit, 232/232 integration (real Postgres/Redis stack per item 34).

    Every test asserting the old sentinel value (`test_lottery_draw_service.py` ×6,
    `test_product_service.py` ×4, `test_user_service.py` ×3) switched to `pytest.raises(...)`.
    Confirmed clean: 393/393 unit, 232/232 integration (real Postgres/Redis stack per item 34).

40. ~~**Unit tests were sending real emails through SendGrid**~~ — **FIXED**. Two compounding bugs:
    - `app/utils/email_sender.py::send_email` only used `settings.DEBUG` to print a dev banner —
      it still called the real SendGrid API afterward regardless, on the assumption that a local
      `SENDGRID_API_KEY` is always a placeholder so the real send just fails harmlessly. That
      assumption doesn't hold once a real key is configured locally (e.g. to test the email flow
      end to end), which is exactly this project's actual local setup: `DEBUG=true` *and* a real
      key. Fixed by `return`ing right after the dev-banner print instead of falling through.
    - `tests/unit/events/test_lottery_draw_service.py`'s win/loss tests never mocked
      `celery_app.send_task` (unlike `test_user_service.py`/`test_auth_service.py`, which already
      did), so every winner/loser `draw_lottery` produces enqueues a real `LOTTERY_WON`/
      `LOTTERY_LOST` email task — which, with a real worker consuming the same Redis broker and
      the `send_email` bug above, gets actually delivered. Fixed at the root rather than patching
      that one file: a new autouse fixture in `tests/unit/conftest.py` mocks
      `app.celery_app.celery_app.send_task` for every unit test, so no test — this one or a future
      one — can reach a real Celery dispatch regardless of whether it remembers to mock it itself.
      Same defense-in-depth reasoning as `tests/conftest.py`'s existing `fake_redis` patch.

    Verified by temporarily poisoning `sendgrid.SendGridAPIClient.send` to raise if ever called
    and running the full unit suite — 393/393 passed, confirming nothing reaches it. `docs/`
    doesn't have a way to verify the second fix (`send_email`'s DEBUG short-circuit) against a live
    SendGrid account from here; reasoned safe instead, since no test exercises `email_sender.py`
    directly and the change only ever short-circuits a branch that previously either silently
    failed (placeholder key) or shouldn't have run at all (real key, which was the actual bug).

41. ~~**Migrated transactional email from SendGrid to Resend**~~ — **FIXED**. `app/utils/email_sender.py`
    now calls `resend.Emails.send(...)` instead of `SendGridAPIClient.send(...)`; same `send_email(to_email,
    subject, body)` signature, same `settings.DEBUG` dev short-circuit (item 40). `Settings.SENDGRID_API_KEY`
    is gone, replaced by `RESEND_API_KEY`; `FROM_EMAIL` is unchanged but now must be on a
    Resend-verified domain (or the sandbox `onboarding@resend.dev`) rather than an arbitrary address.
    `requirements.txt`, `.env.example`, CI (`.github/workflows/test.yml`'s two `SENDGRID_API_KEY`
    secret refs), and `render.yaml` all updated to match.

    While updating `render.yaml`, found a pre-existing gap unrelated to this migration: the
    `i-dolly-backend-worker` service's `envVars` never included `SENDGRID_API_KEY`/`FROM_EMAIL` at
    all (only the web service had them), even though the worker is the process that actually runs
    `app.tasks.email.send_email` and `Settings` has no default for that key — so the worker
    container should have failed to boot on Render whenever it was last (re)deployed from this
    config. Added `RESEND_API_KEY`/`FROM_EMAIL`/`DEBUG` to the worker's `envVars` as part of this
    change; worth confirming on the next real Render deploy that the worker was actually getting
    these some other way (e.g. set by hand in the dashboard, out of sync with this exported file).

    Verification: `py_compile` + `ruff check --select F401,F811,F821` clean; full unit suite
    (393/393) unaffected, since the autouse `celery_app.send_task` mock from item 40 stops any
    test from reaching `email_sender.py` at all. No live Resend account available from here to
    smoke-test an actual delivery — same caveat as item 40's SendGrid verification.

    **Follow-up**: bought `i-dolly-app.site` (Cloudflare Registrar) and verified `mail.i-dolly-app.site`
    as a Resend sending domain — DKIM (TXT), two SPF-related CNAMEs (`rsend.mail`/`send.mail`
    pointing at Resend's `forge.rmta.net` infrastructure), and a DMARC TXT (`_dmarc`, `p=none`), all
    added via Cloudflare DNS with the two CNAMEs set to "DNS only" (a proxied/orange-cloud CNAME
    would have broken verification, since Cloudflare's proxy only speaks HTTP(S)). `.env`'s
    `FROM_EMAIL` updated to `noreply@mail.i-dolly-app.site` — also fixes a bad prior value
    (`i-dolly-backend.onrender.com`, a bare hostname with no `@`, not a valid email address at all).
    With the domain verified, sends are no longer sandbox-restricted to the Resend account owner's
    own inbox — this closes out the "no live account to test against" caveat above for local/manual
    testing, though CI and the deployed Render services still only have a placeholder/unset key
    unless `RESEND_API_KEY`/`FROM_EMAIL` are updated there too (`render.yaml`'s `sync: false` means
    Render's dashboard, not this file, holds the real values).

42. ~~**Email bodies were plain text sent under Resend's `html` param**~~ — **FIXED**.
    `app/utils/email_sender.py`'s `resend.Emails.send(...)` call has always passed `body` as the
    `html` field (true since the SendGrid→Resend migration in item 41), but every
    `EmailTemplate` body in `app/utils/email_templates.py` was plain text with `\n\n` separators —
    HTML collapses bare newlines to spaces, so every email would have rendered as one run-on
    paragraph with no line breaks, and the verification/reset links would have shown as bare
    unclickable URL text instead of a link. Converted all seven templates
    (`EMAIL_VERIFICATION`, `ORDER_PLACED`, `TICKET_CONFIRMED`, `LOTTERY_WON`, `LOTTERY_LOST`,
    `LOTTERY_PAYMENT_CONFIRMED`, `RESET_PASSWORD`) to real HTML: `<p>` per paragraph, `<br>` for
    same-paragraph line breaks, `<a href="{link}">` for the verification/reset links. Every
    interpolated field is either an `EmailStr` validated at the schema boundary (`{email}`) or a
    server-generated value (ids, prices, an HMAC-signed `{link}` token) — none are arbitrary user
    text, so no HTML-escaping was needed on the placeholders themselves.

    Verification: `py_compile` + `ruff check --select F401,F811,F821` clean; full unit suite
    (393/393) — the one test that inspects email body content
    (`test_user_service.py::test_reset_password_process`) only asserts the link substring is
    present, which still holds verbatim inside the new `<a href="...">` markup.

43. ~~**`orders.shippingstatus` was never populated**~~ — **WRONG PREMISE, corrected; the real
    bug was the opposite (duplicate rows) — FIXED**. This item originally claimed nothing ever
    inserted a `shipping_status` row, based on a grep for `ShippingStatus(`. That grep missed
    `payment_service.py`, which imports the model as `ModelShipStatus` and has always inserted one
    in `PaymentService.create_payment` (every checkout, status set by the payment outcome) — and
    `finalize_paypal_payment` inserted *another* on PayPal capture. The "fix" here (a third insert
    in `OrderService.checkout()`) made every order carry 2–3 rows. With `Order.shippingstatus`
    `uselist=False` and no unique constraint, which row loaded was arbitrary — a declined mock
    order carried both `pending` and `cancelled`, so `ship_order` could ship an unpaid order
    (`docs/bugs.md` #1).

    Real fix: `create_payment` is the single creator of the row; the extra insert in `checkout()`
    was removed; `finalize_paypal_payment` now updates the existing row (status + `updated_at`)
    instead of inserting. Backstopped by migration `a9d3f5b7c1e2`, which adds
    `uq_shipping_status_order_id` (no dedupe step — no orders were created while the duplicate-row
    code was live). Regression
    unit test: `test_order_finalize_updates_existing_shipping_status_not_insert`. Verified live
    (2026-09-25): the integration suite's `alembic upgrade head` from empty reached `a9d3f5b7c1e2`,
    `uq_shipping_status_order_id` exists, and all 235 integration tests passed.

    Also added `ShippingStatusResponse.updated_at` (was `status`-only) so an order-detail page can
    show *when* it shipped, not just that it did — this exposed a second, smaller issue:
    `shipping_status.updated_at`'s `server_onupdate=func.now()` documents intent to SQLAlchemy but
    isn't backed by an actual Postgres trigger, so it would never have actually updated on a status
    change. Both `OrderService.update_shipping_status()` (the pre-existing admin free-form override)
    and the new `ship_order()` now set `updated_at` explicitly rather than relying on that.

    Verification: `py_compile` clean; full unit suite (404/404); `ship_order`'s control flow
    (cross-company manager rejected, same-company manager succeeds + notifies, already-shipped
    order rejected) exercised with a mocked session, since Docker was unavailable this session for
    the usual throwaway-Postgres pass — worth a real live-DB run of a full checkout →
    single_placed_order round trip once Docker's back, to confirm end to end rather than at the
    schema/mock layer alone.
39. **Rate-limit tuning pass**, prompted by benchmarking `GET /products/store-page` and finding its
    `5, 60` budget (per-IP) exhausted almost immediately under any real browsing pattern, not just
    an attacker's. Audited every `rate_limit(limit, window, key_func)` call across `app/router`
    and grouped them by what each is actually defending: money/inventory mutations (checkout, cart,
    lottery entry — `3/60`) and auth-abuse surfaces (register, login, forgot-password — `3-10/60`)
    were already correctly tight and left untouched; several self-scoped or public-cached reads
    were sharing that same tight budget with no abuse rationale behind it, just a copy-pasted
    number. Bumped: `GET /products/all`/`GET /products/store-page` `5→30` (cache-backed, 5-min TTL,
    the DB is already protected — this budget was guarding against scraping, not load, and 5/min
    is below normal SPA browsing traffic on one shared IP); `GET /profile/me` `10→60` (fired on
    every SPA navigation/bootstrap); `GET /payment/status*` (all, order, ticket) `5→20` (polled
    during PayPal's async capture flow, §7 — 429ing mid-checkout is the worst place for this to
    bite); `GET /order/single_placed_order/{id}` `3→15` (a plain read that was sitting at the same
    budget as `checkout_order`'s actual mutation, above it in the same file — looked copy-pasted
    rather than deliberate); `GET /notifications/unread-count` `30→60` (explicitly documented as
    polled, `notification.py`'s own comment says "well above" the poll rate — widened the margin);
    `GET /shipping_addresses/fetch` `5→20` (hit during checkout's address-selection step).

    **Separate bug, not a tuning issue**: `GET /shipping_addresses/fetch_byid/{address_id}` was
    keyed on `ip_key`, the only shipping endpoint not using `user_key` — everyone behind the same
    IP shared one bucket for arbitrary users' address-by-id lookups, and a user switching networks
    reset their own. Fixed to `user_key` to match every sibling endpoint on this resource; limit
    left at `5/60` since only the key was wrong, not the number.

    **Gap found while benchmarking, also fixed here**: `GET /products/{id}/detail`, `GET
    /groups/{id}/detail`, and `GET /idols/{id}/detail` had no `rate_limit` dependency at all,
    unlike their sibling cache-backed reads (`/products/all`, `/products/store-page`,
    `/groups/all`, `/idols/all`, all `10-30/60, ip_key`) on the same pattern (item 31/33's per-id
    detail caches). Added `rate_limit(30, 60, ip_key)` to all three, matching the budget already
    used for `/products/all`/`/products/store-page` — a per-id detail page is browsed at least as
    often as a list page, so no reason for a tighter number here.

    **`GET /concerts/{id}/detail`** had the same missing-limiter gap, but couldn't take the flat
    `ip_key` copy the other three got: it's auth-optional (`get_current_user_optional`), which only
    sets `request.state.user` when a token is actually presented (`app/deps/auth.py`) — plain
    `user_key` would raise `AttributeError` on every guest request. Added
    `app/cache/rate_limit.py::user_or_ip_key` (keys on `user.id` when `request.state.user` is set,
    falls back to `ip_key`'s bucket otherwise) and wired `rate_limit(30, 60, user_or_ip_key)` in,
    placed after `current_user`'s `Depends(get_current_user_optional)` in the signature so the
    limiter reads `request.state.user` after it's actually set, not before.

    Manager/admin CRUD (`20/60` uniform across campaigns/album/ticket-type/genre/merch) and
    admin-sensitive actions (`make-admin`/`create-manager`, `3/60`) were reviewed and left as-is —
    authenticated, privileged, not a normal-usage friction point.
40. **Benchmarking `GET /products/store-page` surfaced a latency-under-concurrency question, not
    yet resolved.** Two local runs against the new `30/60` limit: concurrency 1 (15s) gave
    p50/p90/p99/max of 76/88/111/680ms; concurrency 3 (20s) gave 133/220/1735/1853ms — the tail
    grows sharply with concurrency while throughput barely does (~9.7 → ~11.6 req/s, nowhere near
    3x). Confirmed via `grep` that every one of the 161 route handlers across `app/router` is
    plain `def`, not `async def` (the sole `async def` in the tree, `payment.py::_raw_body`, is an
    async dependency for the webhook's raw-body read, not a route handler) — matches
    `architecture.md` §2 exactly, no doc drift there.

    An initial theory (thread-pool/DB-connection-pool contention) doesn't hold up:
    `app/db/session.py` sizes the pool at 10 connections (`pool_size=5, max_overflow=5`) against
    the ~40-thread FastAPI threadpool specifically so a handful of connections serve many
    concurrent requests — 3 concurrent requests is nowhere near either limit, and §2's whole point
    in moving off `async def` was to let requests genuinely run concurrently rather than queue.
    Better-supported, still-unconfirmed hypothesis: CPython's GIL — blocking Redis/Postgres I/O
    releases it while waiting, but the CPU-bound work around it (Pydantic validation, msgpack
    pack/unpack, JSON encoding) doesn't, so concurrent threads can see GIL hand-off delays that a
    single sequential caller never triggers. The pre-existing cold-cache-miss theory (one real
    Postgres round-trip among the cache-hit responses) is separate and still unconfirmed either.
    Neither has been isolated: `benchmark/bench.py`'s `Results` currently blends `200`/`429`
    latencies into one set of percentiles, which hides which requests were actually slow. Next
    step, not yet done: split latency tracking by status code (or add per-request timestamps to
    the CSV output) before drawing a firmer conclusion — flagging so this doesn't get miscited as
    a settled finding.

    **Update — per-status split built and run** (`bench.py` now reports percentiles per status
    code and writes `timestamp,status,latency_ms` rows). Findings, local Docker Compose on Windows:
    - **Floor**: a `429` (one Redis `INCR`+`TTL`, no DB) costs ~88ms p50 at concurrency 1. Redis is
      on the Compose network, so this is environment overhead (Docker Desktop port forwarding,
      single `uvicorn --reload` process), not cache cost. It applies to every request and doesn't
      carry over to Render.
    - **Warm cache-hit cost**: `200` p50 102.6ms vs `429` p50 87.6ms at concurrency 1, so the
      Redis `GET` + msgpack unpack + `StorePageRead` validation + response encoding adds ~15ms.
    - **Under concurrency 3**, `200`s degrade far more than `429`s (p50 ×3.2 vs ×1.4). Direction
      fits the GIL hypothesis (the `200` path has more CPU work), but ~15ms of extra work doesn't
      explain ~230ms of extra latency on its own.
    - **Confound the split exposed**: with a `30/60` per-IP budget, every `200` lands in the first
      seconds of a run and every `429` after, so the comparison is also warm-up vs. steady state.
      At concurrency 3, exactly 3 of 30 `200`s sit above the 688ms p90, which fits a **cache
      stampede**: `CacheService.get_cached_store_page` has no rebuild lock, so N concurrent misses
      all run `ProductService.get_store_page` and all `setex` the same key. Harmless at N=3, but
      at real traffic it repeats every `TTL_SECONDS` (5 min) expiry. **Confirmed** with a cold run
      (`products:store_page` deleted first, concurrency 3): the 3 slowest `200`s were requests
      #1-3, started within 53ms of each other, each ~1.0-1.1s. All three started before any
      finished, so all three necessarily missed the cache and rebuilt it.
    - **The stampede only explains the tail, not the median.** Once the cache was warm (requests
      #4-30), `200`s still took ~300-500ms at concurrency 3 against ~100ms at concurrency 1,
      roughly 3× for 3× the concurrency. Together with throughput barely rising with
      concurrency, this looks like requests are being handled nearly one at a time somewhere.
      Where is still open: the local environment (Docker Desktop networking on Windows,
      `--reload`) and CPU work under the GIL are both candidates. Running the app outside Docker
      without `--reload` would separate them.
    - **Unexplained**: runs cover less time than `--duration`. The cold concurrency-3 run's
      requests span 12.7s of a 20s duration, with no unmeasured gaps inside that span (each
      worker's summed latency ≈ 12.65s). So the missing ~7s falls before the first request or
      after the last one. An earlier concurrency-1 run showed the same thing (34 requests in 15s,
      ~3.5s measured).

## 5. Deliberately deferred — next phase, not forgotten

- **Group/idol CRUD success-path integration coverage** — every group/idol integration test today
  only reaches the RBAC/wiring boundary (401 unauthenticated, 403 wrong role/company, 404
  not-found-in-empty-table); none proves an actual authenticated manager/admin successfully
  creates/updates/deletes their own company's group or idol over real HTTP. `test_permissions.py`'s
  `Factory` would need a `group()` builder (mirrors its existing `idol()`) to build this cheaply.
- **`/payment/status/order/{id}`'s found-case** — only its 401/404 paths are integration-tested
  (item 34); a real found-case needs a full product/category/shipping-address chain behind an
  actual `/order/checkout` call, not built yet. The equivalent ticket-side endpoint
  (`/payment/status/ticket/{id}`) is fully covered, since a real ticket is cheap to stand up
  (concert/venue/ticket_type/campaign, already had a `Factory` shape to reuse).
- ~~**Unit tests for the checkout concurrency/locking paths**~~ — **PARTLY DONE**, and as real
  integration tests against a live Postgres rather than unit tests, which is the stronger form of
  proof for this specific category of bug (see item 1's regression writeup in §4 — the bug was
  invisible to inspection and only surfaced under genuine concurrent transactions).
  `order_service.checkout` and `lottery_draw_service.draw_lottery` (item 8) are now covered —
  `tests/integration/marketplace/test_orders_concurrency.py`,
  `tests/integration/events/test_lottery_concurrency.py`. Still open: `ticket_service
  .checkout_ticket`/`checkout_won_ticket` use the same lock-hold-commit-once pattern against
  `ticket_type.sold_quantity` but have no equivalent race test yet — worth the same treatment
  given item 1's fix shows this pattern can look correct and still have a bypassable lock.
- **Payment failure handling** — the mock gateway's decline path (`simulate_succ=false`) has
  always worked; PayPal's decline path (`finalize_paypal_payment`'s `else` branches, §7) is
  implemented but not yet exercised against a real declined sandbox payment.
- ~~**The direct/"reservation" (non-lottery) checkout flow**~~ — **DONE**:
  `TicketService.checkout_ticket` (`POST /tickets/checkout`) is the real direct-sale purchase
  path — checks `ticket_types.sale_method == 'direct'`, an open `DirectSaleCampaign` window,
  remaining stock, and the same one-live-ticket-per-concert/unresolved-lottery-standing gates the
  lottery path uses, then locks and pays the same way `checkout_won_ticket` does. `add_ticket`
  (admin-only manual issue) remains a separate stopgap, used for the lottery-draw path only.
- **The draw job's actual runtime** — **decided: manager-triggered**, not a Celery Beat scheduled
  task — see §8 for the full plan. The Celery skeleton (`app/celery_app.py`, broker on Redis)
  stays unused for this specific job as a result; it may still end up used for winner-notification
  dispatch (a separate concern from the draw itself, see §8).
- **No sweep job for expired unpaid lottery-won tickets** — designed in `database-design.md`
  §5.2's sequence diagram, not built; the one place this is even lazily discovered today
  (`PaymentService.finalize_paypal_payment`) only covers one narrow path to it. Full writeup,
  including why it's explicitly out of scope for the new checkout/lottery-draw concurrency tests:
  §8's "Known limitation" note.
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
  designed.** Today an ownerless product is a fully legitimate state (`database-design.md`
  §3.15/§6) — nothing enforces or flags it, which is what let item 14's bug exist. Making
  ownership *required* is a policy change, not a bug fix, and collides with product creation being
  deliberately two-step (a bare `Product` first, an ownership row after) — enforcing it at
  creation needs either an atomic creation flow or a `DEFERRABLE` constraint checked at commit.
  Softer alternatives: a `products.status` (`draft`/`published`) gate, or a periodic audit query
  with no DB-level enforcement. Also undecided: does this apply to every product, or should some
  merch stay intentionally ownerless?

## 6. Suggested next steps, in order

1. A real `alembic upgrade head` + endpoint smoke test against live Postgres/Redis — the standing
   gap behind every "verified" claim in this project (§3).
2. ~~Fix the checkout/ticket-inventory race before building the draw job or direct purchase flow
   on top of it~~ — **DONE**, see §4 item 1.
3. Build the draw job (§5/§8), with its concurrency guard designed in from the start.
4. ~~Fill in the missing *primary* fan-only-purchase check at the service layer~~ — **FIXED**.
   `cart_service.add_to_cart`, `order_service.checkout`, `lottery_entry_service.apply_to_lottery`,
   and `ticket_service.add_ticket` each check the buyer's `role == "fan"` before doing anything
   else, raising `FanOnlyPurchaseError` (the existing DB-trigger-backstop exception, reused rather
   than adding a new one).

## 7. PayPal gateway integration — implemented, partially verified

**The core problem the mock gateway's design didn't solve**: it resolves success/failure
synchronously via a `simulate_succ` flag. PayPal can't work that way — it's an async three-step
handoff (create order → buyer approves → server captures) plus a webhook that can arrive before,
after, or instead of the capture call, possibly more than once. Solved by decrementing
stock/capacity only inside `finalize_paypal_payment`, once payment is actually confirmed, with the
capture endpoint and the webhook as two entry points into that one shared function rather than
duplicated logic. Re-running it against an already-resolved payment is a no-op
(`payment.status != PaymentStatus.pending` guard) — that status check is the idempotency
mechanism, not a separate event-id table.

**What shipped**:
1. `app/config/settings.py`: `PAYPAL_CLIENT_ID`/`SECRET`, `PAYPAL_MODE`, `PAYPAL_WEBHOOK_ID`.
   No new dependency beyond `httpx`.
2. `app/utils/paypal_client.py`: `get_access_token()` (OAuth2 client-credentials, cached
   in-process), `create_order()`, `capture_order()`, `verify_webhook_signature()` (posts back to
   PayPal's own verify-webhook-signature endpoint rather than reimplementing cert-chain
   verification), `extract_approval_url()`.
3. Migrations add `'paypal'` to `payment_gateway_enum` and `payment.pg_approval_url`.
4. `PaymentGateway.paypal` and `PaymentResponse.pg_approval_url` in the schema.
5. `order_service.checkout()`/`ticket_service.checkout_ticket()`'s `paypal` branch creates the
   Order/Ticket row pending, calls `create_order()`, stores `pg_order_id`/`pg_approval_url` — no
   stock decrement yet. `finalize_paypal_payment` re-locks the relevant rows
   (`with_for_update()`), checks and decrements stock/capacity *before* calling `capture_order()`
   (an irreversible external side effect — checking after would let PayPal take a buyer's money
   for an order that turns out unfulfillable), then marks everything success and commits once.
   Two endpoints: `POST /payment/paypal/capture/{pg_order_id}` (fast path, authenticated) and
   `POST /payment/paypal/webhook` (reconciliation, signature-verified, no auth). The frontend is
   fully built: `PaypalReturnPage.vue` reads the token off the query string, calls the capture
   endpoint, and renders a real confirmation UI; `PaypalCancelPage.vue` handles the cancel
   redirect. See `docs/api-spec.md` §6 for the full frontend-facing sequence.

**Deviation from the original plan**: a planned `processed_webhook_events` table (idempotency
keyed on PayPal's event id) was dropped — the `payment.status != pending` guard already makes
`finalize_paypal_payment` idempotent regardless of which caller reaches it first or how many
times the webhook re-delivers, with no second table to maintain.

**Verified**: a real PayPal Sandbox ticket checkout end-to-end (create order → approve → capture
→ `Payment`/`Ticket` flip to success/paid), confirmed both locally and against the deployed
Render app (so `PAYPAL_MODE`/`FRONTEND_BASE_URL`/CORS are wired correctly there too).
~~The order-flow (marketplace) checkout hasn't been run end-to-end against real PayPal~~ —
**DONE**: run against real PayPal Sandbox the same way as the ticket flow, same
create-order → approve → capture → `Payment`/`Order` success sequence.

**Not yet verified — known limitations**:
- The webhook path has never received a real or simulated delivery — both a real ngrok tunnel and
  PayPal's own simulator show zero incoming requests, which matches a known PayPal pattern of
  silently dropping delivery to tunnel-flagged domains rather than a confirmed bug in the handler.
  Try `cloudflared` instead of ngrok before assuming the handler code is at fault.
- The decline path (`finalize_paypal_payment`'s `else` branches) is code-reviewed but not
  exercised against a real declined sandbox payment.
- No sweep for abandoned PayPal checkouts — a `pending` order/ticket that's never approved or
  cancelled stays `pending` indefinitely. No stock is incorrectly held (it was never decremented),
  but the row lingers. Whether this needs an expiry job is still open.
- Whether `finalize_paypal_payment` needs a lock against concurrent invocation by both the
  capture endpoint and the webhook for the same order: the `with_for_update()` locks plus the
  pending-status guard appear to close this in practice, but it hasn't been race-tested.

## 8. Manager-triggered lottery draw job — implemented

`PUT /concerts/lottery-draw/{id}` (`app/router/events/concert.py`) enqueues
`app.tasks.lottery.draw_lottery` (`app/tasks/lottery.py`, registered in `celery_app`'s `include`
list), which calls `LotteryDrawService.draw_lottery` (`app/services/events/lottery_draw_service.py`).

**Runtime: a company manager (or admin) triggers the draw via an HTTP action**, scoped to their
own company's concerts — not a Celery Beat cron on `lottery_campaigns.draw_at`. This extends the
same RBAC/company-scoping story the rest of the project uses, and gives an accountable human
action for something that reserves inventory, rather than an unattended scheduled job. `draw_at`
stays on the schema as the fan-facing ETA — it doesn't have to be the instant the draw actually
runs.

**The trigger endpoint enqueues a Celery task rather than running the algorithm inline** — the
draw touches every campaign/entry/preference/ticket_type row for a concert, which doesn't belong
in a request/response cycle. The router stays synchronous and small: validate RBAC, confirm at
least one campaign is `open`, dispatch the task, return `202`. The task opens its own DB session
via `app.db.session.session()` (not FastAPI's request-scoped `get_db`) and calls straight into
the draw algorithm. Trigger granularity is per concert, not per campaign — `database-design.md`
§5.2's rank cascade needs every tier's campaign for one concert drawn together, or a fan's
"at most one ticket per concert" guarantee breaks.

**RBAC**: the same one-level `_manager_scope_violation(current_user, concert.company_id)` check
`concert_service`/`ticket_type_service` use, since concerts carry `company_id` directly.

**Concurrency guard**: `with_for_update()` on every target `ticket_types` row for the concert, the
`lottery_campaigns` rows under them, and their `pending` `lottery_entries`. No explicit lock
ordering — safe today only because every lock in one draw is scoped to that one concert's own
rows, so two concurrent draws can't partially overlap in a way that deadlocks; worth an explicit
order if that scoping assumption ever changes. Only `status='open'` campaigns are eligible, which
makes the endpoint self-idempotent — a double-click or a race between two managers finds nothing
open on the second call.

**Algorithm** (maps to `database-design.md` §5.2's sequence diagram): reject if any target
campaign's entries haven't closed; then for `rank = 1, 2, 3, ...`, gather every tier's `pending`
entries ranked at this rank by users who haven't already won elsewhere in this concert this run,
sample winners up to each tier's remaining capacity, mark them `won` + insert a
`Ticket(status='pending_payment')` + increment `sold_quantity`; after the last rank, every
still-`pending` entry becomes `lost`; flip processed campaigns to `drawn`; one commit at the end.

**Randomness**: `secrets.SystemRandom().sample(candidates, k)`, not the default `random` module or
`ORDER BY random()`. The business rule (no purchase multiplier, every fan gets exactly one shot)
already fixes the method as uniform sampling — what's worth getting right is the source:
`random`'s Mersenne-Twister PRNG is statistically uniform but not cryptographically secure,
`secrets.SystemRandom()` is OS-CSPRNG-backed and a drop-in replacement. Sampling runs in Python,
not SQL, since the cross-rank/cross-tier exclusion bookkeeping is inherently procedural.

**Notifications**: `draw_lottery` writes `lottery_result` (every winner and loser) and, for
winners only, `lottery_payment_reminder` (fired once at draw time, not on a later schedule)
inside the same transaction as the draw itself — cheap same-database inserts, so coupling them to
the draw's commit costs nothing and buys atomicity. Win and loss are **in-app notifications only —
no email**: `draw_lottery` used to also dispatch a `LOTTERY_WON`/`LOTTERY_LOST` email per entry via
`celery_app.send_task`, but that was removed so testing the lottery flow against real seed-fan
email addresses (Resend, not the local dev short-circuit) doesn't spam a real inbox on every draw;
the templates themselves are gone from `EmailTemplate` too, not just unwired. Email still fires for
`lottery_payment_confirmation` once a won ticket is actually paid for
(`PaymentService.finalize_paypal_payment`) — payment success and ticket confirmation stay the
email-worthy events, per-draw win/loss doesn't. A reproducible/auditable draw (logging a seed +
candidate snapshot per rank) was considered and intentionally not built — nothing in this
project's scope models a dispute process.

A separate `lottery_draw_triggered` notification fires earlier and outside this transaction
entirely — from the router, at the moment the manager/admin presses draw
(`ConcertService.notify_managers_of_draw_trigger`, §2's Notifications bullet), before the Celery
task above even runs. It tells every manager at the company a draw is now in flight.

If the task itself then raises — the entries-not-closed-yet check, a closed-campaign race from a
double-click, a real bug — `draw_lottery_task` (`app/tasks/lottery.py`) catches it, rolls back,
looks the concert back up (the local `Concert` object from inside `draw_lottery` is gone once it
raised), and calls `ConcertService.notify_managers_of_draw_failure` for a `lottery_draw_failed`
notification to the same audience, before re-raising the original exception unchanged — so the
failure notification and Celery's own `FAILURE` task state both still happen, neither replaces the
other. On the happy path, `draw_lottery` now also calls
`ConcertService.notify_managers_of_draw_completion` (`lottery_draw_completed`) right after its own
commit — so a manager who wasn't watching the concert's edit page when the draw finished has a
persistent record it actually completed, not just that it started or failed. All three manager
notifications (`lottery_draw_triggered`/`lottery_draw_failed`/`lottery_draw_completed`) carry
`concert_id` only — no per-winner detail — the actual outcome is
`GET /lottery_entries/concert/{concert_id}/results` (`api-spec.md` §Lottery Entries), a
manager-facing endpoint returning every decided entry with the winner's email and their ticket's
payment status/deadline.

`draw_lottery_task`'s Celery return value is also `.model_dump(mode="json")`-serialized rather than
a raw `LotteryResult` — the model wasn't JSON-serializable, so Celery's kombu encoder raised and
recorded the task as `FAILURE` even when the draw itself had already committed successfully; caught
from a real worker log, reproduced by calling the task directly and encoding its return value with
`kombu.utils.json.dumps`, fixed, and re-verified the same way. Separately, `LotteryEntry.drawn_at`
— a real column, exposed in `LotteryEntryRead` and used by the results endpoint above — was never
actually set by `draw_lottery` (only `LotteryCampaign.draw_at` was); found while building that
endpoint, fixed by setting `entry.drawn_at`/`candidate.drawn_at` alongside each status change.

**Placement**: `app/services/events/lottery_draw_service.py`, not folded into
`lottery_campaign_service.py` — the draw is a meaningfully different concern (touching
`LotteryCampaign`/`LotteryEntry`/`LotteryPreference`/`TicketType`/`Ticket`) from plain campaign
CRUD.

**Open question**: should the endpoint gate only on entries being closed (manager has full
discretion on timing), or also require `now() >= draw_at` (trigger becomes "confirm," not full
discretion)? Leaning toward the former; changes what `draw_at` means in the schema's story, so
not decided speculatively here.

**Verification**: implemented and unit/integration-tested; the concurrency guard specifically
(the `with_for_update()` locking described above) is now confirmed against a real live Postgres —
`tests/integration/events/test_lottery_concurrency.py` races two concurrent `draw_lottery` calls
for the same concert and confirms exactly one wins, the loser correctly finds no open campaign
left, and `sold_quantity`/ticket/won-entry counts stay consistent (§4 item 1's regression writeup
has the full context — that same test-writing pass is what caught a real oversell bug elsewhere in
checkout). Still open: a full multi-fan draw (more than the 3 candidates per tier that race test
seeds) hasn't been exercised against a live Postgres.

**Known limitation — no sweep job for expired unpaid tickets** (`database-design.md` §5.2's
sequence diagram, "Sweep job for expired unpaid tickets"): a fan who wins the lottery but never
pays before `tickets.payment_deadline_at` should have that slot released
(`tickets.status='expired'`, `ticket_types.sold_quantity -= 1`, optionally re-drawn from the lost
pool) so it doesn't sit held forever. The only place this is even checked today is
`PaymentService.finalize_paypal_payment`'s lazy discovery (its own comment: "no sweep job exists
yet ... so this is the one place that does it") — which only fires if someone happens to hit that
specific PayPal-finalize path for that exact ticket; nothing else ever reads
`payment_deadline_at`. Not built, not scheduled anywhere — see §5's deferred list. **Excluded from
the concurrency tests added alongside item 1's fix** (`test_orders_concurrency.py`,
`test_lottery_concurrency.py`): those race `order_service.checkout` and `draw_lottery`, both real
code paths — a sweep job that doesn't exist yet has nothing to race.
