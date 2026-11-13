# Bugs / code smells — audit backlog

English | [日本語](bugs_JP.md)

Findings from a static read-through (2026-09-24) of auth, checkout/payment, ticketing, lottery,
cache and storage code. **Not reproduced against a live app or test run** — each item is traced in
the code, not observed at runtime. Tick items off (or move them into `project_status.md` §4) as
they're fixed.

Every open item was re-read against the code on 2026-11-13 (again static, not run): all of them
still hold. That pass corrected line references, added the **Review** notes below, and added
#30–#32.

## 🔴 Critical

- [x] **1. Duplicate `shipping_status` rows per order** — FIXED (see `project_status.md` §4
  item 43; migration `a9d3f5b7c1e2`, since applied against Postgres in the integration suite and CI). `OrderService.checkout`
  (`order_service.py:98`) now inserts one, but `PaymentService.create_payment`
  (`payment_service.py:54`) already did, and `finalize_paypal_payment` (line 210) adds another.
  No `UNIQUE(order_id)`; `Order.shippingstatus` is `uselist=False`, so which row loads is
  arbitrary — a declined order can read as `pending` and be shipped. `project_status.md` item 43's
  premise ("nothing inserted a shipping_status row") is wrong. Fix + add a unique constraint.
- [ ] **2. Deleting a product deletes order history.** `order_items.product_id` is
  `ON DELETE CASCADE` (`models/marketplace/order.py:34`) and `delete_product` hard-deletes
  (`product_service.py:201`). Any manager can do this to ownerless merch. Same class as item 17.
- [x] **3. Cart IDOR.** **FIXED**: the query now also filters by `Cart.user_id`. `CartService.remove_cart` (`cart_service.py:51`) filters only by
  `Cart.id`; `user_id` is accepted but unused — any user can delete anyone's cart row.
- [x] **4. Lottery apply ignores entry window and campaign status.** `_stage_entry`
  (`lottery_entry_service.py:31`) never checks `entry_start_at`/`entry_end_at`/`status == open`;
  no trigger does either. A post-draw entry stays `pending` forever and then blocks direct-sale
  purchase for that concert via `_unresolved_lottery_entry`.
  **FIXED in the service**: `_stage_entry` loads the campaign `FOR SHARE` and rejects applies unless
  `status == open` and now is inside the entry window. The share lock serializes an apply against
  the draw's `FOR UPDATE`; `tests/integration/events/test_lottery_apply_window.py` races the two
  against real Postgres (and fails if the lock is removed). Still open: no DB trigger backstop, and
  any entries already stuck as `pending` on a non-open campaign need a one-off cleanup.
- [x] **5. Editing preferences breaks the concert's draw.** `set_preferences`/`clear_my_preferences`
  work even with pending entries; the draw's `next(p for p in preferences ...)`
  (`lottery_draw_service.py:55`) then raises `StopIteration` and aborts for everyone. Also allows
  re-ranking after entries close.
  **FIXED**: `set_preferences`/`clear_my_preferences` run `_check_ranking_change_allowed`. Campaigns
  of the current and new tiers are loaded `FOR SHARE`; any closed/drawn campaign rejects the change;
  every newly ranked tier needs an open campaign whose window has started (fans rank through an
  existing campaign); removing a tier with a pending entry is rejected.
  `tests/integration/events/test_lottery_preference_guard.py` covers it against real Postgres,
  including a race against the draw's lock (fails if the lock is removed).
- [x] **6. Same fan can win twice in one tier.** With `max_entries_per_user > 1`,
  `sample(candidates, ...)` can pick two entries of one user (`won_user_ids` is only checked when
  building candidates) → `trg_tickets_one_per_concert` fails the whole commit.
  **MITIGATED**: the field was removed from `LotteryCampaignCreate`/`Update`, so it stays at the
  DB default of 1. The draw itself still doesn't dedupe by user; fix that before exposing the field
  again. Any rows already set above 1 are unchanged; check with
  `SELECT id FROM lottery_campaigns WHERE max_entries_per_user > 1`.
- [x] **7. IP rate limits spoofable.** `ProxyHeadersMiddleware(trusted_hosts="*")` (`main.py:70`)
  makes uvicorn 0.38 take the *leftmost* `X-Forwarded-For` hop, which the client controls
  (Render appends, doesn't strip). Rotating the header bypasses login/register limits.
  **Fix planned:** `docs/plans/rate-limit-client-ip.md`.
  **Review:** closer to High than Critical — it defeats the login/register limits but exposes no
  data by itself.
  **FIXED in code** (`project_status.md` §4 item 49): `ProxyHeadersMiddleware` is gone;
  `rate_limit.client_ip()` reads the entry `TRUSTED_PROXY_HOPS` from the right of
  `X-Forwarded-For`, and login and forgot-password also have a per-email limit. Still to do on
  Render: measure the hop count and set `TRUSTED_PROXY_HOPS` (`deployment.md` §7) — until then the
  default `0` puts every visitor in one bucket.
- [ ] **8. PayPal capture under row locks, no reconciliation.** `finalize_paypal_payment` calls
  `capture_order` (network, 10s timeout) while holding `FOR UPDATE` on payment/ticket_type/products
  (`payment_service.py:153`, `:182`). If PayPal captures but the response times out or our commit
  fails → charged, DB `pending`. The webhook re-calls `capture_order` → 422 already captured →
  500 → retried for 3 days, never resolves. Webhook should apply the event, not re-capture.
  Design it together with #30 and #32 (same function, same PayPal calls).

## 🟠 High

- [x] **9. `async def` routes doing sync work.** All 161 async handlers call sync SQLAlchemy,
  bcrypt, PayPal httpx and boto3 → block the event loop. Plain `def` routes would use the threadpool.
  **HANDLERS FIXED**: every route handler (163 today) is `def` (`architecture.md` §2). The 6 that
  awaited something were converted too: `storage.save()` is now sync, and the webhook reads its
  body in an async dependency. Verified via TestClient that uploads and the webhook run in the
  threadpool. S3 uploads now read at most MAX+1 bytes (fixes the whole-file-in-memory smell below).
  - ~~Set `pool_size`/`max_overflow` explicitly in `app/db/session.py`~~ — done (5 + 5, 10s timeout)
- [x] **10. `DEBUG` defaults to `True`** (`settings.py`), contradicting `deployment.md` and the
  `email_sender.py` comment. An env missing `DEBUG` prints reset tokens to logs and sends no email.
  **FIXED**: `DEBUG` now defaults to `False`, matching `deployment.md`.
- [ ] **11. Redis outage → 500s.** `CacheService` has no `RedisError` handling. Invalidation runs
  after commit, so checkout/payment 500 on an order that actually succeeded.
  **Fix planned:** `docs/plans/redis-outage.md` (fail-open reads, best-effort invalidation and
  email dispatch, client timeouts).
- [ ] **12. Abandoned direct-sale PayPal ticket locks the fan out.** `pending_payment` counts as
  live (`ticket_service.py:54`) but direct tickets have no deadline/sweep.
  **DEFERRED**: to be fixed later, with #26 and #27.
- [ ] **13. Resale cap counts cancelled/declined orders** (`order_service.py`, no status
  filter). ~~Computed before the lock (concurrent checkouts can both pass)~~ — **race FIXED**:
  `checkout` now runs the cap check after the `FOR UPDATE` on the cart's products, and
  `fn_enforce_resale_cap` takes a `pg_advisory_xact_lock` on (buyer, product) before its sum
  (migration `d4a7c9e2f1b5`), so the trigger holds on its own too. Race-tested in
  `tests/integration/marketplace/test_resale_cap_concurrency.py`. The status-filter half is still
  open. Abandoned PayPal
  checkouts make this worse: each one leaves a `pending` order that counts toward the cap forever
  (#27), so a fan can hit `ResaleCapExceededError` without owning a unit. Count only `confirmed`
  orders.
  **OUT OF SCOPE**: the user-cancel path (`cancel_placed_order`) isn't used by the frontend; not in
  current scope. Note that declined mock payments (`payment_service.py:34`) and abandoned PayPal
  orders (#27) still count toward the cap without that endpoint.
  **Review:** the fix is wider than a service filter. `fn_enforce_resale_cap` sums every order
  with no status filter either, so it needs its own migration. And once only `confirmed` orders
  count, a fan can open several `pending` PayPal orders that each pass the cap and capture them
  all — `finalize_paypal_payment` has to re-check the cap before capturing.
- [x] **14. `cancel_placed_order` doesn't restock, refund, or bust the product cache.**
  **OUT OF SCOPE**: the frontend doesn't use this endpoint; not in current scope.
  **Review:** the route is still live. `PATCH /order/cancel/{order_id}` (`router/marketplace/order.py:80`)
  has no rate limit and lets a fan cancel their own paid, unshipped order with no refund or
  restock. Remove or disable the route until the service is finished.
  **MITIGATED** (`project_status.md` §4 item 50): the route is no longer registered, so nothing
  can call the function. The function itself is unchanged; finish it (refund, restock, cache)
  before registering a route for it again.
- [x] **15. Cart price drift.** Re-adding an item updates `total_price` from the current price but
  leaves `Cart.price` stale (`cart_service.py` add_to_cart); checkout uses `total_price` for the
  order total and `price` for line items → they don't reconcile.
  **FIXED**: re-adding an item reprices the row (`price` and `total_price` both from the current price).
- [x] **16. Emails dispatched before commit** in `checkout_ticket` / `checkout_won_ticket`.
  **FIXED**: both checkouts send the confirmation email only after `commit_or_raise`; unit tests check the order
  and that a failed commit sends nothing (they fail against the old code).
- [x] **17. Webhook `KeyError`** on `resource.supplementary_data.related_ids.order_id` for any
  event type lacking it → 500 → PayPal retries.
  **FIXED**: `paypal_client.order_id_from_webhook` reads the order id from `CHECKOUT.ORDER.*` (`resource.id`)
  or `PAYMENT.CAPTURE.*` (`supplementary_data`) events; anything else gets a 200 and is ignored.
  What happens after an order id is found is unchanged (#8).
- [x] **26. Unpaid PayPal orders can be shipped.** The PayPal path creates the order's
  `shipping_status` row as `pending` before payment (`payment_service.py:51`), and `ship_order`
  checks only the shipping status, not `order.status` (`order_service.py:202`). An abandoned or
  not-yet-captured order shows up on the manager orders page and can be marked shipped. Require
  `order.status == confirmed` in `ship_order`.
  **Review:** no longer deferred — the guard doesn't depend on #12 or #27 (one check plus a test).
  `update_shipping_status` (`order_service.py:164`) needs the same check.
  **FIXED** (`project_status.md` §4 item 50): `ship_order` rejects any order that isn't
  `confirmed` with `400 order_not_paid`, and so does the admin `update_shipping_status` for every
  target status except `cancelled`.
- [ ] **30. PayPal `create_order` runs under row locks.** Same class as #8, at checkout rather than
  capture. `OrderService.checkout` locks the cart's products `FOR UPDATE` (`order_service.py:69`)
  and `checkout_ticket` locks the user and the ticket type (`ticket_service.py:91`, `:99`); both
  then call `create_order` (network, 10s timeout) through `create_payment` /
  `create_ticket_payment` (`payment_service.py:46`, `:94`) before committing. A slow PayPal call
  blocks every other checkout of that product or tier. Found in the 2026-11-13 review.
- [x] **28. `GET /shipping_addresses/fetch_byid/{id}` always 500s, and has no ownership check.**
  The route (`app/router/marketplace/shipping.py:30`) has no `get_current_user` dependency but its
  limiter uses `user_key`, which reads `request.state.user` → `AttributeError` (the limiter only
  catches `RedisError`) → 500 on every call. Confirmed with `TestClient` (2026-09-29). Behind that,
  `ShippingService.get_address_by_id` filters only by id, so once the 500 is fixed it becomes an
  IDOR on other users' addresses. Fix: add `get_current_user` and filter by `user_id`, like the
  sibling `update`/`delete` routes.
  **FIXED** (`project_status.md` §4 item 47): the route now requires login and filters by owner.
  The sibling `update`/`delete` queries had the same hole (`user_id==user_id`, always true) and
  were fixed with it.

## 🟡 Medium

- [ ] **18.** `change_password_process` doesn't revoke refresh tokens (reset does).
  **Review:** low impact today — `create_tokens` already revokes every other token at login, so
  the only live token at that point is the one in use. It matters when that token is the stolen one.
- [ ] **19.** Password-reset JWTs are reusable until expiry (no `jti` / password-hash binding).
- [ ] **20.** Refresh tokens stored plaintext; every login revokes all other sessions
  (`auth_service.py` `create_tokens`).
  **Review:** only the plaintext storage is a defect. One session per user is the documented
  design (see the comment in `create_tokens`).
- [x] **21.** `get_current_user`: `uuid.UUID(payload.get("sub"))` 500s on missing `sub`; unknown
  user returns 404 instead of 401.
  **FIXED**: a missing or malformed `sub` and an unknown user all return 401 (`None` for
  `get_current_user_optional`).
- [ ] **22.** Rate limiter `INCR` + `EXPIRE` aren't atomic (crash between → key never expires);
  `user_key` implicitly depends on `get_current_user` running first.
  **Half fixed**: the counter is created with its TTL and incremented in one `MULTI` transaction
  (`SET key 0 EX window NX` + `INCR`), so it can't exist without an expiry. The `user_key`
  ordering dependency is still open.
- [ ] **23.** Paginated pages return `count=len(data)` (page size, not total)
  (`order_service.py:267`, `ticket_service.py:281`, `product_service.py:477`); manager orders page
  loads every product and order id into memory.
- [ ] **24.** Draw is O(entries × preferences) plus O(ranks × campaigns × entries).
- [ ] **25.** If `notify_managers_of_draw_completion` fails after commit, the Celery task's
  `except` notifies managers the draw *failed*. Anything after `commit_or_raise` in `draw_lottery`
  triggers it: the completion notification's own commit, or `delete_cached_concert_detail` when
  Redis is down (#11). Managers see "failed" for a draw that committed, Celery records the task as
  failed, and the failure notification's commit can itself fail and mask the original error. Fix:
  treat post-commit steps as best-effort (log, don't re-raise) so only errors before the commit
  reach the task's failure path.
  **Fix planned:** `docs/plans/lottery-draw-post-commit.md` (move post-commit steps into the task).
- [ ] **27. Abandoned PayPal marketplace orders stay `pending` forever.** If the fan never approves
  on PayPal, `finalize_paypal_payment` never runs: the order, its payment and its shipping status
  stay `pending` with no deadline or sweep. No stock is held and the cart isn't cleared, so the fan
  can re-checkout, but the stale orders clutter order history and the manager orders page, feed the
  resale cap (#13), and look shippable (#26). Same root cause as #12 (no expiry for PayPal pending
  state); fix them together.
  **DEFERRED**: to be fixed later, with #12 and #26.
- [ ] **31. Stock gone between PayPal approval and capture leaves everything pending.** When the
  tier is sold out or a product is short at capture time, `finalize_paypal_payment` returns `None`
  without changing anything (`payment_service.py:142`, `:180`): the fan, who already approved on
  PayPal, gets a 404, and the ticket or order stays `pending`. Nothing was captured, so no money
  is lost, but it feeds #12 and #27. Mark the payment failed and cancel the ticket/order instead.
  Found in the 2026-11-13 review.
- [ ] **32. Capture success is read from the order status only.** `finalize_paypal_payment` treats
  the capture response's top-level `status == "COMPLETED"` as paid (`payment_service.py:154`,
  `:183`) and never reads the capture's own status
  (`purchase_units[].payments.captures[].status`), which can be `PENDING` or `DECLINED` on a
  completed order. Not reproduced against the sandbox. Check the capture status too.
  Found in the 2026-11-13 review.
- [x] **29. `manager-*-page` reads have no auth and no server-side company scoping.**
  `GET /concerts/manager-events-page`, `/groups/manager-groups-page`,
  `/idols/manager-idols-page`, `/idols/manager-idol-form-page`,
  `/products/manager-products-page` and `/products/manager-product-form-page` take no auth
  dependency; the product ones filter by a client-supplied `company_id`. The data is the same as
  the public listings, so nothing new leaks today, but they skip the RBAC every other manager
  route has and have no rate limit. `GET /order/manager-orders-page` is the exception and is
  scoped correctly.
  **FIXED** (`project_status.md` §4 item 48): all six require `require_manager_or_admin`, are
  rate-limited (`30/60s`, `user_key`), and a manager only gets their own company's rows.

## 🔵 Code smells

- Money as `float` (`total_price=float(...)`, `with_tax(float(...))`).
- ~~Read-only `/payment/status/*` endpoints use `PATCH`~~ — fixed: they're `GET` (frontend
  `payment.service.js` must switch in the same release).
- ~~Empty lists return 404~~ — fixed: every list endpoint returns `[]` and page endpoints an
  empty page object (2026-09-29).
- ~~`/account/verify` returns 401 for "already verified"~~ — fixed: `409` for already verified,
  `400` for a bad token or unknown user (`ConflictError` added to `app/exception/common.py`).
- No `logging` anywhere in `app/` — `print()` only; email failures swallowed, never retried.
- ~~`verify_token_and_get_user_id` / `verify_rtoken_and_get_user_id` near-duplicates~~ — fixed:
  merged into `jwt_manager.decode_email_token(token, expected_type)`.
- ~~`CacheService` ↔ services import each other~~ — fixed: invalidation split into
  `app/cache/invalidation.py` (Redis only); `CacheService` inherits it (`architecture.md` §2).
- ~~Upload extension taken from client filename — `.html` with `Content-Type: image/png` gets
  served as HTML by `StaticFiles` on the API origin (stored XSS)~~ — fixed: the extension comes
  from the whitelisted content type (`storage.IMAGE_EXTENSIONS`). ~~S3 path reads the whole upload
  before size check~~ (fixed with #9).
- ~~PayPal `pg_payment_id` set from `generate_mock_id()` instead of the real capture id (needed for
  refunds)~~ — fixed: set from the capture response via `paypal_client.capture_id_from_response`.
- ~~`MAX_RANK` upper-case local; `create_order` currency default `"USD"` while all callers pass
  `"JPY"`; leftover tutorial comment in `main.py`~~ — fixed: renamed to `max_rank`, default is
  `"JPY"`, and the comment is gone.

## Suggested order (updated 2026-11-13)

Fixed so far: #1, #3, #4, #5, #6 (mitigated), #7, #9, #10, #14 (mitigated), #15, #16, #17, #21,
half of #22, #26, #28, #29, and eight code smells.

1. ~~Quick wins: #10, #15, #16, #17~~ (done).
2. ~~New quick wins: #26 require `confirmed` before shipping; #14 remove or disable the cancel
   route~~ (done).
3. **Security:** ~~#28 broken/unguarded address lookup~~ (done); ~~#7 spoofable IP rate limits~~
   (done in code; set `TRUSTED_PROXY_HOPS` on Render); ~~#29 unauthenticated manager pages~~ (done).
4. **Data integrity and money:** #2 product delete wipes order history (migration to `RESTRICT` +
   soft delete or block).
5. **Planned:** #11 Redis outage handling (plan in `docs/plans/redis-outage.md`) together with
   #25 (plan in `docs/plans/lottery-draw-post-commit.md`) — the Redis fix removes one trigger of
   #25.
6. **Auth:** #18, #19, then the plaintext-storage half of #20.
7. **PayPal pending state:** #12 (abandoned ticket locks the fan out) and #27 (abandoned orders
   never expire) with a scheduled sweep, plus #31 and #13 (the cap can only count `confirmed`
   orders once pending ones expire or are re-checked at capture).
8. **Needs design first:** #8 PayPal capture under locks / webhook reconciliation, with #30 and
   #32.
9. **Whenever convenient:** #22, #23, #24.
