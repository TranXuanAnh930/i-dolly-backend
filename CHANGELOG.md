# Changelog

English | [日本語](CHANGELOG_JP.md)

The version the backend is running is `__version__` in `app/__init__.py`. The API reports it in
the `/` response and in the OpenAPI docs (`/docs`). Work lands on `develop`, and a release is one
commit on `main` named `release X.Y.Z`; there are no git tags.

**To cut a release:** move the items under *Unreleased* into a new section, set `__version__` to
the same number, then merge to `main` with the `release X.Y.Z` commit.

Sections up to 1.4.2 were reconstructed on 2026-11-14 from the release commits on `main` and the
`develop` commits that landed before each one, so they summarize rather than list every change.
Dates are the release commit dates (JST). Bug numbers refer to `docs/bugs.md`.

## Unreleased (on `develop`, reported as 1.4.2)

- **Fixed — products are soft-deleted (#2).** Deleting a product sets `is_active = false`
  instead of removing the row, so past orders keep their lines; new
  `PATCH /products/activate/{id}`. `orders_items.product_id` and `products.category_id` are now
  `ON DELETE RESTRICT`, and a category with products can't be deleted (`category_in_use`).
  Migrations `a1c5e7f9b3d2`, `b3d7f1a5c9e4`, `c5e9a3b7d1f6`.
- **Fixed — unpaid orders can't be shipped (#26).** The ship route and the admin status override
  require a `confirmed` order (`order_not_paid`).
- **Removed — `PATCH /order/cancel/{order_id}` (#14).** It cancelled paid orders with no refund or
  restock; the service function is kept, unregistered.
- **Fixed — user-keyed rate limits no longer depend on dependency order (#22).**
- Removed the temporary proxy-hops log line used to measure `TRUSTED_PROXY_HOPS`.
- **Added — logging.** The app logs through Python's `logging` instead of `print()`
  (`app/config/log_config.py`), at the new `LOG_LEVEL` setting (default `INFO`), in the same
  format under the API and, via Celery's handler, in the worker. A failed email is now logged with
  its traceback; it is still not retried.
- **Security — changing the password ends other sessions (#18).** Every refresh token is revoked,
  and `PUT /profile/change-password` now answers like `POST /account/refresh` (`access_token` in
  the body, new refresh cookie) so the caller stays logged in. The frontend must send it with
  credentials (`docs/frontend-tasks/password-session-and-reset-links.md`).
- **Security — password-reset links work once (#19).** The link carries a fingerprint of the
  password hash it was issued for and is refused once the password has changed. Links emailed
  before this release are refused too.
- **Fixed — abandoned PayPal checkouts no longer lock fans out (#12, #27).** A fan's own pending
  PayPal checkout is cancelled when they check out again (same concert for tickets, any pending
  order for the marketplace), or through the new `POST /payment/paypal/cancel/{pg_order_id}` when
  they back out on PayPal. Lottery wins keep their seat until their deadline.

## 1.4.2 — 2026-11-14

- **Security — IP rate limits can't be bypassed with a forged `X-Forwarded-For` (#7).** The client
  IP is read `TRUSTED_PROXY_HOPS` entries from the right (3 on Render); `ProxyHeadersMiddleware`
  removed. New per-email limits: 5 failed logins per 15 minutes, 3 password-reset requests per
  hour.
- Bug backlog re-checked against the code; items #30–#32 added.

## 1.4.1 — 2026-10-01

- `Makefile` wrapping the common Docker and dev commands.
- Study pages (`study/`) on the project's architecture and design topics.

## 1.4.0 — 2026-10-01

- **Contact page:** FAQ instant answers from the Claude API (`claude-haiku-4-5`), with the contact
  form as the fallback.
- **Security:** manager settings pages require manager/admin and are scoped by company (#29);
  shipping-address reads and writes are scoped to the owner (#28).
- **Fixed:** the resale-cap race in checkout and in its trigger.
- Empty list endpoints return `200 []` instead of `404`; error-handling refactor.
- Japanese seed script (`scripts/seed_ja.py`) and Japanese translations of the README and docs.
- More tests (money, RBAC scoping, router paths), test-coverage report, updated ERD.

## 1.3.6 — 2026-09-27

- Per-endpoint rate-limit budgets.
- Order confirmation emails fixed; code smells and a Redis bug fixed.

## 1.3.5 — 2026-09-26

- Ticket-checkout concurrency fix; PayPal capture id stored for refunds.
- Shipping-address table put to use; a round of bug fixes; bug backlog (`docs/bugs.md`) added.

## 1.3.4 — 2026-09-22 and 2026-09-23

Released twice under the same number.

- Row locking for order and lottery checkout (concurrency).
- Separate test database; cache staleness fixes; batch lottery entries.
- Lottery result page; lottery failure notifications; lottery emails replaced by in-app
  notifications.

## 1.3.3 — 2026-09-21

- Email moved from SendGrid to Resend, with new templates and a sending domain.
- Password reset by emailed link instead of a pasted token.
- Cached detail pages; error messages moved to enums; more tests.

## 1.3.2 — 2026-09-19

- Exception classes for error handling; typed response schemas instead of `{msg: ...}` dicts.
- Email notifications for checkout and ticket purchases.
- Docs and code comments rewritten.

## 1.3.1 — 2026-09-19

- Cache and rate-limiter fixes.

## 1.3.0 — 2026-09-16

- Code reorganised into domain modules, with services as classes.

## 1.2.0 — 2026-09-15

- PayPal checkout (sandbox) with capture and signed webhook.
- Ruff linting; Celery memory fixes; Render plan changed to Starter to run the worker.

## 1.1.0 — 2026-09-13

- Lottery draw and direct-sale campaigns.
- In-app notifications, polled by the frontend.
- Business-logic and fetching-performance fixes.

## 1.0.3 — 2026-09-11

- Separate admin and manager pages; orders and sales endpoints.
- Managers can't change product or event prices and times; capacity and time locks on tickets
  and concerts.
- Unit and integration tests; `render.yaml` blueprint.

## 1.0.2 — 2026-09-10

First deploy. The fork of the e-commerce boilerplate turned into the idol-ticket domain: UUID
keys, Celery and notifications, fan-only purchasing, orders and payments with tax, ticket
payments, merch products, soft-deleted groups and idols, password reset by email, CI.
