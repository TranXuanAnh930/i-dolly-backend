# Test Coverage Report

A snapshot of what the test suite covers, measured rather than estimated. It's kept separate from
`project_status.md` because it's a point-in-time report: re-run the command below and update the
tables when the numbers move meaningfully, rather than editing individual figures by hand.

**Measured:** 2026-09-29, on `refactor/add-test-coverage` after merging `develop` (`e100b11`) and
the manager-page auth fix. **Result:** 923 passed, 0 failed, 0 skipped. **94.6% line coverage** of
`app/` (5,907 / 6,242 statements), up from 85.3% (745 tests, 6,211 statements) on `develop` at
`3abc98b`, the baseline for every "Before" column below.

## 1. How it was measured

The same way CI's `test` job runs it (`.github/workflows/test.yml`), locally:

- PostgreSQL 16 and Redis running locally; `DATABASE_URL` pointing at a scratch database. The
  suite never touches it directly: `tests/conftest.py` redirects every connection to
  `<name>_test`, and `tests/integration/conftest.py` drops, recreates and migrates that database
  (`alembic upgrade head` from empty) once per session.
- Dummy values for the JWT/Resend secrets. No test sends email or reaches PayPal.
- Command: `pytest --cov=app --cov-report=term-missing`.

This is **line coverage only**. Branch coverage isn't enabled (`--cov-branch`), so a line with an
`if` that only ever ran one way still counts as covered.

## 2. Totals

| Suite | Tests | Line coverage on its own | Needs Postgres? |
|---|---:|---:|---|
| `tests/unit` | 531 | 66% | No (mocked `Session`, `fakeredis`) |
| `tests/integration` | 392 | — | Yes (real Postgres; Redis is `fakeredis`) |
| **Both** | **923** | **94.6%** | |

The unit suite on its own reaches 66% because routers, real SQL and DB triggers are exercised
only by the integration suite. The two suites are complementary; neither is meant to reach the
total alone.

## 3. By package

| Package | Statements | Before | After |
|---|---:|---:|---:|
| `app/services` | 2498 | 89.4% | 96.9% |
| `app/router` | 1589 | 68.1% | 86.2% |
| `app/schema` | 887 | 98.6% | 99.5% |
| `app/db` | 541 | 100.0% | 100.0% |
| `app/cache` | 327 | 97.6% | 98.8% |
| `app/utils` | 195 | 58.5% | 85.1% |
| `app/exception` | 81 | 79.0% | 100.0% |
| `app/deps` | 48 | 100.0% | 100.0% |
| `app/config` | 40 | 100.0% | 100.0% |
| `app/tasks` | 31 | 0.0% | 100.0% |
| `app/celery_app` | 5 | 100.0% | 100.0% |
| **Total** | **6242** | **85.3%** | **94.6%** |

`app/db` and `app/schema` are near 100% mostly because model and schema modules are declarative
and execute at import. Their coverage says little about correctness; the trigger and constraint
behavior behind them is what the integration tests below check.

## 4. What this pass added, and what each suite proves

Files that moved by 5 points or more:

| File | Before | After |
|---|---:|---:|
| `app/utils/email_sender.py` | 0.0% | 100.0% |
| `app/tasks/lottery.py` | 0.0% | 100.0% |
| `app/tasks/example.py` | 0.0% | 100.0% |
| `app/tasks/email.py` | 0.0% | 100.0% |
| `app/utils/storage.py` | 37.9% | 100.0% |
| `app/router/talent/idol.py` | 43.4% | 100.0% |
| `app/router/marketplace/products.py` | 45.8% | 99.3% |
| `app/router/talent/group.py` | 47.9% | 100.0% |
| `app/router/marketplace/shipping.py` | 57.1% | 100.0% |
| `app/exception/db_triggers.py` | 59.5% | 100.0% |
| `app/services/marketplace/order_service.py` | 60.1% | 95.9% |
| `app/services/marketplace/product_service.py` | 59.4% | 94.9% |
| `app/router/events/concert.py` | 63.2% | 97.4% |
| `app/router/events/ticket.py` | 65.5% | 90.8% |
| `app/router/marketplace/order.py` | 74.7% | 88.6% |
| `app/cache/rate_limit.py` | 82.4% | 94.1% |
| `app/services/events/ticket_service.py` | 83.4% | 94.7% |
| `app/schema/marketplace/products.py` | 91.8% | 100.0% |

### Integration (real HTTP + Postgres unless noted)

- **`events/test_won_ticket_checkout.py`**: `checkout_won_ticket` called at the service level,
  one `Session` per call, like the other race tests. Sequential cases: paying leaves
  `sold_quantity` untouched (the draw already counted the seat), a declined payment leaves the
  ticket payable for a retry, and it rejects another fan's ticket, a direct-sale ticket, an
  already-paid ticket, a wrong amount and a reused idempotency key. Past the deadline, the ticket
  expires and releases its seat. **Races**: a double submit pays exactly once; the same
  idempotency key twice records one payment; three concurrent attempts past the deadline release
  the seat exactly once (`sold_quantity` 1 → 0, never -1 or -2).
- **`marketplace/test_order_fulfillment.py`**: fan cancel (only while `pending`/`processing`,
  only their own order), the manager Ship button scoped by company through
  `album_details`/`merch_details` (mixed-company orders, ownerless products, admin override,
  terminal statuses), the `order_shipped` notification, the admin shipping-status override
  (cannot revive a cancelled order), and the manager orders page. A manager only sees their own
  company's line items and totals and can't widen that with `?company_id=`.
- **`marketplace/test_product_management.py`**: create-with-detail (album/merch) scoped to the
  manager's company, deactivated-owner and missing-reference rejection, invalid detail
  combinations, image upload into a temp dir, image replace/update/delete scoping, all-or-nothing
  bulk add, the manager pages (a manager's `company_id` is ignored in favour of their own; the
  form page's idol/group pickers are scoped too), sales history, and artist
  resolution/recommendations on the product detail page.
- **`marketplace/test_shipping_addresses.py`**: ownership on every by-id read and write. This
  suite found a real IDOR (`project_status.md` §4 item 47, fixed in the same branch); 5 of its 10
  tests fail against the pre-fix code.
- **`talent/test_idol_group_management.py`**: idol/group create, update, soft delete, reactivate
  and image upload for owning managers and admins; cross-company 403s; group-in-another-company,
  deactivated-group and unknown-color validation; inactive rows disappearing from public reads;
  the manager idol/group settings pages returning only the manager's company (every company for
  an admin).
- **Manager settings pages** (`test_permissions.py::test_manager_settings_page_role_gate`): all
  seven `manager-*-page` reads return 401 without a token, 403 for a fan and 200 for a manager or
  admin. The company scoping of each is checked in the suite for its domain (above and below).
- **`events/test_ticket_and_concert_endpoints.py`**: which service exception maps to which status
  code for both ticket checkouts and the admin manual issue, `/tickets/mine`, per-viewer
  personalization on the concert detail page (guest vs. holder vs. other fan), performer
  assign/remove scoping, the lottery-draw trigger (enqueues the Celery task, notifies managers),
  and the manager events page returning only the manager's concerts (venues stay shared).

Shared fixture: **`tests/integration/_seed.py`** (`seed`, registered in
`tests/integration/conftest.py`) inserts rows directly, mints a JWT for any role, and tears down
with bulk `DELETE`s in reverse order. Postgres' `ON DELETE CASCADE` then also removes rows a test
created through the API. The existing "empty table returns 404" tests (e.g. `test_idols.py`) still
pass after these suites run, which checks that the cleanup is complete.

### Unit

- **`test_tasks.py`**: the three Celery tasks run in-process. For the lottery draw task: success
  returns a JSON-safe dict; on failure it rolls back, notifies managers (or skips that if the
  concert is gone), re-raises, and always closes the session.
- **`test_email_sender.py`**: `DEBUG` prints instead of sending; the Resend payload; a delivery
  failure is logged, not raised.
- **`test_db_triggers.py`**: every trigger/constraint message maps to its typed exception and HTTP
  status; `diag.message_primary` is preferred; unknown DB errors come back unchanged; the
  commit/flush helpers always roll back.
- **`test_storage.py`** (extended): local backend writes and the size-limit cleanup; S3 backend
  with a mocked boto3 client (upload, size limit, missing bucket, all three public-URL shapes);
  `get_storage()` backend selection and caching.

## 5. What's still not covered

Files under 90%:

| File | Coverage | Missed statements |
|---|---:|---:|
| `app/utils/paypal_client.py` | 51.7% | 28 |
| `app/router/talent/idol_color.py` | 55.3% | 21 |
| `app/router/marketplace/category.py` | 59.5% | 15 |
| `app/router/talent/position.py` | 62.1% | 25 |
| `app/router/marketplace/album_detail.py` | 64.6% | 17 |
| `app/router/marketplace/merch_detail.py` | 64.6% | 17 |
| `app/router/events/lottery_campaign.py` | 67.2% | 20 |
| `app/router/events/ticket_type.py` | 67.9% | 18 |
| `app/router/marketplace/genre.py` | 68.5% | 17 |
| `app/router/events/lottery_entry.py` | 72.2% | 15 |
| `app/router/events/direct_sale_campaign.py` | 73.8% | 16 |
| `app/router/talent/management_company.py` | 80.9% | 9 |
| `app/router/shared/inquiry.py` | 82.4% | 3 |
| `app/services/events/lottery_entry_service.py` | 83.7% | 16 |
| `app/router/marketplace/order.py` | 88.6% | 9 |

- **`paypal_client.py`**: `get_access_token`, `verify_webhook_signature` and the HTTP error paths
  of `create_order`/`capture_order` make real calls to PayPal's API. Covering them means mocking
  `requests` responses. The end-to-end sandbox checkout in `project_status.md` §7 is the real
  verification here.
- **The small CRUD routers** (idol colors, categories, positions, album/merch details, genres,
  campaigns, ticket types, lottery entries): their services are unit-tested and their role gates
  are integration-tested. What's missing is mostly the `except ServiceError → HTTPException`
  lines, which are the same pattern as the routers now fully covered.
- **`lottery_entry_service.get_draw_results_for_concert`**: the draw-results read (14 lines) has
  no test at either level.
- **`order.py`'s `checkout_order`**: the `PaymentFailedError` branch and the post-commit
  confirmation email. `single_placed_order` has no found-case test.

## 6. Limits of these numbers

- Coverage shows which lines ran, not that the assertions around them are right. The shipping
  IDOR in §4 is the example: `shipping_service.py` was already at 100% line coverage from
  mocked-`Session` unit tests while any fan could delete anyone's address.
- Redis is `fakeredis` in both suites, so rate-limit and cache behavior is checked against its
  implementation, not a real Redis server.
- This run was local. CI runs the same command on GitHub Actions against `postgres:16`, but
  these numbers come from the local run, not a CI artifact.
