# Bugs / code smells — audit backlog

Findings from a static read-through (2026-09-24) of auth, checkout/payment, ticketing, lottery,
cache and storage code. **Not reproduced against a live app or test run** — each item is traced in
the code, not observed at runtime. Tick items off (or move them into `project_status.md` §4) as
they're fixed.

## 🔴 Critical

- [x] **1. Duplicate `shipping_status` rows per order** — FIXED (see `project_status.md` §4
  item 43; migration `a9d3f5b7c1e2`, not yet run against a live DB). `OrderService.checkout`
  (`order_service.py:98`) now inserts one, but `PaymentService.create_payment`
  (`payment_service.py:54`) already did, and `finalize_paypal_payment` (line 210) adds another.
  No `UNIQUE(order_id)`; `Order.shippingstatus` is `uselist=False`, so which row loads is
  arbitrary — a declined order can read as `pending` and be shipped. `project_status.md` item 43's
  premise ("nothing inserted a shipping_status row") is wrong. Fix + add a unique constraint.
- [ ] **2. Deleting a product deletes order history.** `order_items.product_id` is
  `ON DELETE CASCADE` (`models/marketplace/order.py:34`) and `delete_product` hard-deletes
  (`product_service.py:206`). Any manager can do this to ownerless merch. Same class as item 17.
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
- [ ] **7. IP rate limits spoofable.** `ProxyHeadersMiddleware(trusted_hosts="*")` (`main.py:75`)
  makes uvicorn 0.38 take the *leftmost* `X-Forwarded-For` hop, which the client controls
  (Render appends, doesn't strip). Rotating the header bypasses login/register limits.
  **Fix planned:** `docs/plans/rate-limit-client-ip.md`.
- [ ] **8. PayPal capture under row locks, no reconciliation.** `finalize_paypal_payment` calls
  `capture_order` (network, 10s timeout) while holding `FOR UPDATE` on payment/ticket_type/products
  (`payment_service.py:159`, `:190`). If PayPal captures but the response times out or our commit
  fails → charged, DB `pending`. The webhook re-calls `capture_order` → 422 already captured →
  500 → retried for 3 days, never resolves. Webhook should apply the event, not re-capture.

## 🟠 High

- [ ] **9. `async def` routes doing sync work.** All 161 async handlers call sync SQLAlchemy,
  bcrypt, PayPal httpx and boto3 → block the event loop. Plain `def` routes would use the threadpool.
  **HANDLERS FIXED**: all 162 route handlers are `def` (`architecture.md` §2). The 6 that
  awaited something were converted too: `storage.save()` is now sync, and the webhook reads its
  body in an async dependency. Verified via TestClient that uploads and the webhook run in the
  threadpool. S3 uploads now read at most MAX+1 bytes (fixes the whole-file-in-memory smell below).
  Still open:
  - ~~Set `pool_size`/`max_overflow` explicitly in `app/db/session.py`~~ — done (5 + 5, 10s timeout).
  - Add the missing `checkout_ticket` race test, now that routes really run concurrently.
- [x] **10. `DEBUG` defaults to `True`** (`settings.py`), contradicting `deployment.md` and the
  `email_sender.py` comment. An env missing `DEBUG` prints reset tokens to logs and sends no email.
  **FIXED**: `DEBUG` now defaults to `False`, matching `deployment.md`.
- [ ] **11. Redis outage → 500s.** `CacheService` has no `RedisError` handling. Invalidation runs
  after commit, so checkout/payment 500 on an order that actually succeeded.
- [ ] **12. Abandoned direct-sale PayPal ticket locks the fan out.** `pending_payment` counts as
  live (`ticket_service.py:54`) but direct tickets have no deadline/sweep.
- [ ] **13. Resale cap counts cancelled/declined orders** (`order_service.py:71`, no status
  filter), and is computed before the lock (concurrent checkouts can both pass).
- [ ] **14. `cancel_placed_order` doesn't restock, refund, or bust the product cache.**
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

## 🟡 Medium

- [ ] **18.** `change_password_process` doesn't revoke refresh tokens (reset does).
- [ ] **19.** Password-reset JWTs are reusable until expiry (no `jti` / password-hash binding).
- [ ] **20.** Refresh tokens stored plaintext; every login revokes all other sessions
  (`auth_service.py` `create_tokens`).
- [ ] **21.** `get_current_user`: `uuid.UUID(payload.get("sub"))` 500s on missing `sub`; unknown
  user returns 404 instead of 401.
- [ ] **22.** Rate limiter `INCR` + `EXPIRE` aren't atomic (crash between → key never expires);
  `user_key` implicitly depends on `get_current_user` running first.
- [ ] **23.** Paginated pages return `count=len(data)` (page size, not total); manager orders page
  loads every product and order id into memory.
- [ ] **24.** Draw is O(entries × preferences) plus O(ranks × campaigns × entries).
- [ ] **25.** If `notify_managers_of_draw_completion` fails after commit, the Celery task's
  `except` notifies managers the draw *failed*.

## 🔵 Code smells

- Money as `float` (`total_price=float(...)`, `with_tax(float(...))`).
- Read-only `/payment/status/*` endpoints use `PATCH`.
- ~~Empty lists return 404 (`/order/fetch_placed_order`, `/payment/status/all`)~~ — fixed, both return `[]`.
- `/account/verify` returns 401 for "already verified".
- No `logging` anywhere in `app/` — `print()` only; email failures swallowed, never retried.
- ~~`verify_token_and_get_user_id` / `verify_rtoken_and_get_user_id` near-duplicates~~ — fixed:
  merged into `jwt_manager.decode_email_token(token, expected_type)`.
- ~~`CacheService` ↔ services import each other~~ — fixed: invalidation split into
  `app/cache/invalidation.py` (Redis only); `CacheService` inherits it (`architecture.md` §2).
- Upload extension taken from client filename (`storage.py:46`) — `.html` with
  `Content-Type: image/png` gets served as HTML by `StaticFiles` on the API origin (stored XSS).
  Derive ext from the whitelisted content type. ~~S3 path reads the whole upload before size check~~ (fixed with #9).
- PayPal `pg_payment_id` set from `generate_mock_id()` instead of the real capture id (needed for
  refunds).
- `MAX_RANK` upper-case local; `create_order` currency default `"USD"` while all callers pass
  `"JPY"`; leftover tutorial comment in `main.py`.

## Suggested order (updated 2026-09-26)

Fixed so far: #1, #3, #4, #5, #6 (mitigated), most of #9, and three code smells.

1. ~~Quick wins: #10, #15, #16, #17~~ (done).
2. **Security:** #7 spoofable IP rate limits (plan in `docs/plans/rate-limit-client-ip.md`).
3. **Data integrity and money:** #2 product delete wipes order history (migration to `RESTRICT` +
   soft delete or block); #14 cancel doesn't restock, together with #13 resale cap counting cancelled
   orders.
4. **Needs design first:** #8 PayPal capture under locks / webhook reconciliation; #12 abandoned
   direct-sale PayPal ticket locks the fan out; #11 Redis outage handling.
5. **Test debt:** #9's `checkout_ticket` race test.
