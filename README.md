# i-dolly-backend

An idol-concert **ticket reservation** backend with an **album/singles marketplace**, built as a
**portfolio project** to showcase backend engineering: schema design, layered API architecture,
migration discipline, and RBAC. It started as a generic FastAPI e-commerce website and has been
turned, incrementally, into the idol-ticket domain — idols/groups, venues/concerts, lottery-based
ticket sales, and an album/merch marketplace layered on the original cart/order/payment
plumbing.

This is **not** a production system, and the docs below say so plainly where it isn't finished —
see [Known limitations](#known-limitations).

---

## Documentation

The `docs/` folder is the source of truth for anything not obvious from the code itself:

| File | What's in it |
|---|---|
| [`docs/database-design.md`](docs/database-design.md) | Schema (ERD), table-by-table notes, the RBAC matrix, the lottery business logic |
| [`docs/architecture.md`](docs/architecture.md) | How the code is organized: router → service → model layering, conventions |
| [`docs/project_status.md`](docs/project_status.md) | What's actually built vs. still open, known issues, verification method |
| [`docs/api-spec.md`](docs/api-spec.md) | Every route the backend exposes, grouped by frontend use case |
| [`docs/deployment.md`](docs/deployment.md) | How to deploy: Render (API + worker), Supabase (Postgres), S3-compatible storage, Render Key Value (Redis) |

---

## Domains

- **Identity** — role-based access (`admin` / `manager` / `fan`), company-scoped managers.
- **Talent** — management companies, idol groups, idols, idol colors, positions.
- **Events & ticketing** — venues, concerts, ticket types (lottery or direct sale), lottery
  preferences/campaigns/entries, issued tickets. Ticket tiers are **capacity-based, not
  seat-mapped** — a deliberate scope decision, not a shortcut (see `database-design.md`'s intro).
- **Marketplace** — products/categories extended with album/single/EP details, merch details
  (covers lightsticks and other official branded merch), genres — reusing the original
  cart/order/payment/shipping machinery.

## Tech stack

- **FastAPI** (Python 3.12) + **Pydantic v2** for request/response schemas
- **PostgreSQL** via **SQLAlchemy 2.0** ORM, **Alembic** for migrations (one linear chain)
- **Redis** for caching (msgpack-serialized) and rate limiting
- **Celery** worker (Redis-backed broker/result backend) — runs the manager-triggered lottery
  draw as a real background job; a Render Background Worker in production
- **JWT** auth — short-lived access tokens + rotating refresh tokens, httponly cookies
- **Mock payment gateway** for local dev, plus a **PayPal** integration (sandbox-verified for
  ticket checkout) — see [Known limitations](#known-limitations) for what's still unverified there
- **SendGrid** for transactional email
- Local disk / S3-compatible object storage abstraction for idol/product images
- **Docker Compose** for local dev; **GitHub Actions** for CI — a `lint` job (`ruff check .`) and
  a separate `test` job (Postgres + Redis services, Alembic migrations, pytest + coverage)

Full detail and reasoning: [`docs/architecture.md`](docs/architecture.md) §1.

## What's actually built

- **UUID primary keys everywhere** — no sequential integer ids, so resources can't be enumerated
  by guessing `/products/search/2`, `/products/search/3`, etc.
- Identity/RBAC, company-scoped managers
- Full CRUD (ORM + schema + service + router) for groups, idols, idol colors, positions, venues,
  concerts, ticket types, lottery preferences/campaigns/entries, tickets, album details, genres,
  merch details
- Local/S3 image uploads for idols and products
- 12 database triggers enforcing money/fairness invariants (fan-only purchasing, the anti-resale
  cap, concert ticket-capacity, the lottery entry cap, and more)
- **Manager-triggered lottery draw** (`PUT /concerts/lottery-draw/{id}`) — runs the rank-cascade
  draw algorithm asynchronously in a Celery worker, with row-level locking so two triggers for the
  same concert can't double-draw it
- **In-app notifications** (order/ticket/lottery confirmations, lottery results, password reset,
  and more) — a polled feed (`GET /notifications/mine`, `/unread-count`), deliberately no
  WebSocket/SSE layer; email dispatch for these is not yet built
- **PayPal checkout**, alongside the mock gateway, for real (sandbox) payment processing
- Idempotency keys on both checkout endpoints, so a retried/double-clicked request can't create a
  duplicate charge
- Soft-delete (deactivate/reactivate) for groups and idols instead of a hard `DELETE`
- An idempotent seed script (`scripts/seed.py`) with a full fictional roster of idols, groups, venues,
  concerts, and marketplace products

Detailed, current status — including what's *not* built yet, like emailing any of the
notifications above, the ETL/analytics pipeline, and a full audit trail on the PayPal decline/
webhook paths: [`docs/project_status.md`](docs/project_status.md) §2 and §5.

## Known limitations
- Rate-limit coverage now spans all 25 router files by an explicit tier policy
  (`docs/architecture.md` §3) rather than ad hoc per-route judgment — but the policy itself (which
  tier a route belongs to, and its exact limit/window) is a portfolio-scoped judgment call, not a
  formally load-tested one.

Full list, ordered by how much each matters — including everything above that's already been
fixed (the checkout race, the rate-limiter key collision, webhook idempotency, and more):
`docs/project_status.md` §4.

---

## Getting started (Docker)

### Prerequisites
- Docker + Docker Compose

### 1. Clone and configure
```bash
git clone https://github.com/TranXuanAnh930/i-dolly-backend.git
cd i-dolly-backend
cp .env.example .env
```
Fill in `.env` — at minimum a JWT secret, and a SendGrid key if you want email flows to work end
to end (the app runs locally without a valid key, but email sending won't). The mock payment
gateway needs no third-party keys; a PayPal Sandbox app's client id/secret are only needed if
you want to exercise the real PayPal checkout path instead.

### 2. Start the stack
```bash
docker compose up --build
```
This starts the FastAPI app, PostgreSQL, Redis, and a Celery worker, and runs
`alembic upgrade head` on boot. The worker is what actually runs a triggered lottery draw
(`PUT /concerts/lottery-draw/{id}`) — without it the endpoint returns "scheduled" but the draw
never executes.

### 3. Explore the API
```
http://localhost:8000/docs
```

### 4. (Optional) Seed sample data
```bash
docker compose exec app python scripts/seed.py
```
Populates a full fictional roster — management companies, idol groups, venues, concerts, ticket
types, and marketplace products. Idempotent — safe to re-run.

### 5. Run tests
```bash
docker compose exec app pytest --cov=app
```

### 6. Run linting
```bash
pip install -r requirements-dev.txt
ruff check .
```
Runs outside the container (no DB/Redis needed) — `requirements-dev.txt` pulls in `ruff` on top of
the regular dependencies. Same command CI runs on every push/PR.

### 7. Stop the stack
```bash
docker compose stop
```
Keeps database data intact.

---

## License

No license file yet — all rights reserved by default until one is added.
