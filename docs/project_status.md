# Project Status

A snapshot of what's built, what's verified, and what's still open — read this before assuming
something exists or is finished. `database-design.md` (same folder) is the schema/business-logic
design; `architecture.md` is how the code is organized; this file is the "where are we right
now" layer, and the one most likely to go stale — update it whenever a feature actually lands or
a known issue gets fixed, don't let it drift into aspirational state.

## 1. Current migration state

**Chain head: `bfadb696c92a`** (`change_shipping_postal_code_to_string`) — 56 migrations, one
linear chain, no branches. Up through `a3f7c9e2b6d4` (`add_password_reset_to_notification_type`),
applied and confirmed against a real Postgres instance: `alembic upgrade head` ran clean from
empty, `alembic current` reported the head revision, and the `notifications` table/enum matched
the models. The notification feature was also exercised over real HTTP end to end (password reset
→ notification created → read → unread-count clears), and the per-route rate limiter was confirmed
firing under load (a 30/60s budget returns `429` past the 30th request). The app is now also
deployed against a real Supabase Postgres (§3) — migrations run clean there through the current
head. The two most recent migrations (`54347349d0f2`, `bfadb696c92a` — item 5's schema-type fix)
have only been verified statically (`py_compile`, `alembic`'s own revision-chain check) so far, not
yet re-run against Supabase.

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
  (`database-design.md` §3.19) covering 8 event types, one nullable FK per referenced entity kind.
  Producers fire inline (no cron/Beat job): `order_service.checkout()`,
  `ticket_service.checkout_ticket()`/`checkout_won_ticket()`, `user_service.verify_rtoken()`, and
  `lottery_draw_service.draw_lottery()` (result for every winner and loser, plus a payment
  reminder for winners, fired at draw time rather than on a schedule closer to the deadline).
  Every write lands in the same commit as the event it describes. Fan-facing API:
  `GET /notifications/mine`, `GET /notifications/unread-count` (polled, no WebSocket/SSE layer),
  `POST /notifications/{id}/read`, `POST /notifications/read-all` — self-scoped, rate-limited.
  `lottery_registered`/`event_reminder` still have no producer. `notifications.status`/`sent_at`
  sit at `pending`/`null` forever regardless — that pair tracks a push-to-inbox step this table
  itself doesn't drive (see Email dispatch below, a separate path).
- **Email dispatch**: every transactional email — verification link, order placed, ticket
  confirmed, lottery win, lottery loss, lottery ticket payment confirmed — goes through
  `celery_app.send_task("app.tasks.email.send_email", ...)`, picked up by the worker task in
  `app/tasks/email.py`, which calls `app/utils/email_sender.py`'s SendGrid wrapper. Subject/body
  text for each lives in `app/utils/email_templates.py`'s `EmailTemplate` enum (`.subject`,
  `.render(**fields)`) rather than inline at each call site. Replaces the original
  `BackgroundTasks.add_task` approach (verification email only) — that couldn't extend to
  `draw_lottery`'s win/loss mail, since a Celery task has no request-scoped `BackgroundTasks` to
  hang a send off of. This is independent of the in-app `notifications` table above: both fire off
  the same triggering events, but one doesn't feed the other.
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
12. **Seeded accounts share a hardcoded, publicly-committed password** — `scripts/seed.py`
    creates an admin, three managers, and four fans all with the same password, written in plain
    text in the file's own docstring. Fine for a throwaway local dev DB; not fine the moment
    `scripts/seed.py` runs against a real deployed database — anyone reading the repo could then
    log in as admin. Not fixed: randomize the seeded password before ever seeding a real
    deployment, or don't seed it at all.
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
    `Literal[False]` branch to cache around, unlike the store-facing pages. The two products pages
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
- **Unit tests for the checkout concurrency/locking paths** (`ticket_service.checkout_ticket`/
  `checkout_won_ticket`, `order_service.checkout`) — the interview-defensible part of item 1's
  overselling-race fix (why the row lock has to be held for the whole operation, why UUID-ordering
  the `order_service` lock acquisition prevents deadlock). Per this project's own convention for
  this category of logic, that reasoning needs to come from actually writing the tests, not from
  having them handed over already passing — see the coverage pass note in §3 for what *was*
  covered in the same session this gap was identified.
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
1. `app/config/settings.py`: `PAYPAL_CLIENT_ID`/`SECRET`, `PAYPAL_MODE`, `PAYPAL_WEBHOOK_ID`,
   `BASE_URL`. No new dependency beyond `httpx`.
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
Render app (so `PAYPAL_MODE`/`BASE_URL`/`FRONTEND_BASE_URL`/CORS are wired correctly there too).
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
the draw's commit costs nothing and buys atomicity. Win and loss also each dispatch an email via
`celery_app.send_task` (§2's Email dispatch) once the transaction's in-app inserts are queued — a
one-time notice at draw time, not a recurring deadline-proximity reminder, which stays out of
scope. A reproducible/auditable draw (logging a seed + candidate snapshot per rank) was considered
and intentionally not built — nothing in this project's scope models a dispute process.

**Placement**: `app/services/events/lottery_draw_service.py`, not folded into
`lottery_campaign_service.py` — the draw is a meaningfully different concern (touching
`LotteryCampaign`/`LotteryEntry`/`LotteryPreference`/`TicketType`/`Ticket`) from plain campaign
CRUD.

**Open question**: should the endpoint gate only on entries being closed (manager has full
discretion on timing), or also require `now() >= draw_at` (trigger becomes "confirm," not full
discretion)? Leaning toward the former; changes what `draw_at` means in the schema's story, so
not decided speculatively here.

**Verification**: same standing gap as §3 — implemented and unit/integration-tested, but not yet
confirmed with a real multi-fan draw against a live Postgres.
