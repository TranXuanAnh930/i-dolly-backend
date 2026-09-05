# Project Status

A snapshot of what's built, what's verified, and what's still open — read this before assuming
something exists or is finished. `database-design.md` (same folder) is the schema/business-logic
design; `architecture.md` is how the code is organized; this file is the "where are we right
now" layer, and the one most likely to go stale — update it whenever a feature actually lands or
a known issue gets fixed, don't let it drift into aspirational state.

## 1. Current migration state

40 migrations, one linear chain, no branches. Current head: **`10f9dfa05636`**
(`extend_idol_colors_and_genres` — adds 17 more `idol_colors` rows and 5 more `genres` rows
needed for the expanded seed roster below; previous head was `019b674bf0c1`,
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
cache the first time it ran). `seed.py` needed no changes — it already wires foreign keys via
ORM-returned `.id`/name lookups, never a literal integer.

## 2. What's built

- **Identity/RBAC**: `users.role`/`company_id`, `management_companies`, `require_admin`/
  `require_manager_or_admin` (`app/deps/auth.py`), company-scoping helpers on every
  company-owned resource's service.
- **Talent**: `groups`, `idols`, `idol_colors`, `positions`/`idol_positions` — full ORM + schema +
  service + router for all four, company-scoped CRUD.
- **Events & ticketing**: `venues`, `concerts`/`concert_performers`, `ticket_types`,
  `lottery_preferences`, `lottery_campaigns`, `lottery_entries`, `tickets` — full ORM + schema +
  service + router for all seven. `tickets` creation is admin-only (a manual stopgap — see §4).
- **Marketplace**: `categories.is_resale_capped`, `album_details`, `genres`/`album_genres`,
  `lightstick_details` — full ORM + schema + service + router.
- **Image uploads**: `idols.profile_image_url` / `products.image_url`, a local/S3 storage
  abstraction (`app/utils/storage.py`), inline upload on `POST /idols/add` and
  `POST /products/add_product` (now `multipart/form-data`, a breaking change from the original
  JSON body), plus `POST /idols/{id}/image` and `POST /products/{id}/image` to replace an image
  later. Full detail: `database-design.md` §9.
- **Seed data** (`seed.py`, repo root): idempotent test-data script — 3 management companies
  (Nova Entertainment, Starlight Media, Kuroyuri Records), 8 users, 5 idol groups spanning
  J-Pop/city-pop/anime-tie-in/gothic/vocaloid-adjacent styles plus 3 solo idols (22 + 3 = 25
  idols total, all Japanese, each with an invented personality blurb), 6 venues, 6 concerts, 18
  ticket types across lottery + direct sale methods, 5 categories, a 20-item marketplace (10
  albums/singles/EPs with genres, 8 lightsticks, 2 plain merch items), 2 lottery campaigns with
  preferences + entries, 1 manually-issued ticket — run via `docker compose exec app python
  seed.py`. Idol portraits and product covers are pushed through the real
  `get_storage().save()` pipeline from `tests/fixtures/{idols,products}/` — procedural
  placeholder art (Pillow gradients/patterns/monograms, no AI image generation was available in
  this environment), not real character art; see `tests/fixtures/README.md`.
- **12 DB triggers / 8 trigger functions** enforcing the money/fairness invariants
  `database-design.md` §4 lists deliberately (fan-only purchasing, the anti-resale cap, concert
  ticket-capacity, the lottery entry cap, the preference-required check, the lottery
  preference/concert match, the album/lightstick mutual-exclusivity pair).

## 3. Verification method (and its limit)

No live Postgres/FastAPI/network access has been available in either environment this project has
been built in — confirmed repeatedly via failed `pip install` attempts (403 from a proxy). Every
round of changes has instead been verified with:

1. A full `py_compile` sweep across `app/`, `main.py`, and `alembic/`.
2. An AST-based scan of every ORM model's `ForeignKey` targets and
   `relationship(back_populates=...)` pairs (currently: 28 model classes, no issues).
3. An AST-based scan of every intra-app `from app.X import Y` statement, confirming the imported
   name actually exists in its target module (currently: 125 files scanned, no issues).

**None of this exercises real SQL or a running app.** `alembic upgrade head` against a real
Postgres, followed by hitting each endpoint (ideally via `seed.py`'s data), is still the
outstanding step before any of this should be treated as production-verified — it has not been
done yet for anything built so far, including the ticketing/lottery/marketplace tables and the
image-upload feature.

## 4. Known issues / tech debt (fix alongside the surrounding code, not standalone)

Ordered roughly by how much each matters to the idol-ticket domain specifically. Items marked
FIXED were pre-existing bugs in the forked boilerplate, closed during this project — not
newly introduced.

1. **Checkout is not one atomic transaction, and has a stock-overselling race** —
   `order_service.checkout()` locks each `Product` row, then `payment_service.create_payment()`
   does its own `db.commit()` mid-flow, releasing the locks; a second loop re-locks and
   decrements without re-checking sufficiency. `ticket_types.sold_quantity` inherits the exact
   same pattern once ticket issuance is built on top of `checkout()` — the ticket-domain failure
   mode is **selling the same seat twice**. Fix before, not after, wiring the draw job / direct
   purchase flow to real inventory decrements.
2. **The rate limiter's key doesn't include the route** (`app/cache/rate_limit.py`) — every
   endpoint sharing a `key_func` shares one Redis counter. Currently a minor annoyance; becomes a
   real problem the moment a high-value, bot-targeted endpoint (a ticket drop, a lottery-entry
   endpoint) needs its own independent budget. Fix by folding the route into the key before
   building anything scalper-sensitive on top of this.
3. ~~`app/db/base.py` didn't import every model~~ — **FIXED**. `Base` now lives in
   `app/db/base_class.py`; `app/db/base.py` is a pure aggregator. See `architecture.md` §5 for
   the convention this establishes going forward.
4. **Webhook handling isn't idempotent** — `payment_service.process_razorpay_webhook` re-applies
   on every delivery (Razorpay retries webhooks). Harmless today; **must** be fixed before a
   webhook can mint a ticket, since a replay would then mint a second one. Key the "already
   handled" check off the Razorpay event id before wiring ticket issuance to this path.
5. **Minor schema type inconsistencies**: `OrderItem.price` is `Integer` while `Product.price` is
   `Float` (truncates fractional prices in order history); `ShippingAddress.postal_code` is
   `Integer`, which breaks for alphanumeric postal codes (UK, Canada, Japan).
6. **CORS `allow_origins` is hardcoded** to a Vue dev port in `main.py` — needs to become
   configurable per environment once there's a real frontend origin.
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

Several smaller items from the original boilerplate audit (UTF-16 `requirements.txt`, a
category-update authorization bug, secrets traveling as query params, no `.dockerignore`, a
missing `UNIQUE` on `Category.name`) were found and fixed earlier in this project and aren't
repeated here — see git history / earlier `CLAUDE.md` versions if the detail is needed.

## 5. Deliberately deferred — next phase, not forgotten

- **Payment failure handling** — every trigger and flow so far assumes success (mock gateway).
- **The direct/"reservation" (non-lottery) checkout flow** — the schema supports it
  (`ticket_types.sale_method = 'direct'`), but only the lottery path has a sequence diagram
  (`database-design.md` §5.2) and only `tickets`' admin-only manual-issue endpoint exists so far.
- **The draw job's actual runtime** — scheduled task, queue worker, or admin-triggered action;
  nothing has been chosen. The schema only commits to `lottery_campaigns.draw_at`/`status`.
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

## 6. Suggested next steps, in order

1. A real `alembic upgrade head` + endpoint smoke test against live Postgres/Redis — the
   standing gap behind every "verified" claim in this project so far (§3), and now the specific
   thing that would confirm §4 item 9's trigger-message matching actually works against real
   Postgres error text, not just AST/compile checks.
2. Fix the checkout/ticket-inventory race (§4 item 1) before building the draw job or direct
   purchase flow on top of it — it's much cheaper to fix before other code depends on its current
   (broken) behavior than after.
3. Build the draw job (§5), with its concurrency guard designed in from the start.
4. Fill in the missing *primary* fan-only-purchase check at the service layer
   (`cart_service.add_to_cart`, `order_service.checkout`, `lottery_entry_service.
   apply_to_lottery`, `ticket_service.add_ticket` currently have no `current_user.role == "fan"`
   check at all — `database-design.md` §4.1 calls the DB trigger a *backstop* to a service-layer
   check, but today the trigger is the *only* thing stopping an admin/manager from buying
   something or entering a lottery). Found while fixing §4 item 9; deliberately left as a
   separate follow-up rather than folded into that fix, since it's a distinct gap (missing
   authorization logic) from what item 9 was about (clean error translation for the trigger that
   already exists as the backstop).
