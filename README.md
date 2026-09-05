# i-dolly-backend

An idol-concert **ticket reservation** backend with an **album/singles marketplace**, built as a
**portfolio project** to showcase backend engineering: schema design, layered API architecture,
migration discipline, and RBAC. It started as a generic FastAPI e-commerce boilerplate
([`VinayParmar555/E-commerce`](https://github.com/VinayParmar555/E-commerce), forked) and has been
turned, incrementally, into the idol-ticket domain — idols/groups, venues/concerts, lottery-based
ticket sales, and an album/lightstick marketplace layered on the original cart/order/payment
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

---

## Domains

- **Identity** — role-based access (`admin` / `manager` / `fan`), company-scoped managers.
- **Talent** — management companies, idol groups, idols, idol colors, positions.
- **Events & ticketing** — venues, concerts, ticket types (lottery or direct sale), lottery
  preferences/campaigns/entries, issued tickets. Ticket tiers are **capacity-based, not
  seat-mapped** — a deliberate scope decision, not a shortcut (see `database-design.md`'s intro).
- **Marketplace** — products/categories extended with album/single/EP details, lightstick
  details, genres — reusing the original cart/order/payment/shipping machinery.

## Tech stack

- **FastAPI** (Python 3.12) + **Pydantic v2** for request/response schemas
- **PostgreSQL** via **SQLAlchemy 2.0** ORM, **Alembic** for migrations (one linear chain)
- **Redis** for caching (msgpack-serialized) and rate limiting
- **JWT** auth — short-lived access tokens + rotating refresh tokens, httponly cookies
- **Razorpay** SDK for payments, plus a mock gateway for local dev/tests
- **SendGrid** for transactional email
- Local disk / S3-compatible object storage abstraction for idol/product images
- **Docker Compose** for local dev; **GitHub Actions** for CI (Postgres + Redis services,
  Alembic migrations, pytest + coverage)

Full detail and reasoning: [`docs/architecture.md`](docs/architecture.md) §1.

## What's actually built

- **UUID primary keys everywhere** — no sequential integer ids, so resources can't be enumerated
  by guessing `/products/search/2`, `/products/search/3`, etc.
- Identity/RBAC, company-scoped managers
- Full CRUD (ORM + schema + service + router) for groups, idols, idol colors, positions, venues,
  concerts, ticket types, lottery preferences/campaigns/entries, tickets, album details, genres,
  lightstick details
- Local/S3 image uploads for idols and products
- 12 database triggers enforcing money/fairness invariants (fan-only purchasing, the anti-resale
  cap, concert ticket-capacity, the lottery entry cap, and more)
- An idempotent seed script (`seed.py`) with a full fictional roster of idols, groups, venues,
  concerts, and marketplace products

Detailed, current status (including what's *not* built yet, like the actual draw job and the
direct/non-lottery checkout flow): [`docs/project_status.md`](docs/project_status.md) §2 and §5.

## Known limitations

This project has been verified with `py_compile` sweeps and AST-based static checks, **not**
against a live Postgres/Redis instance (see `docs/project_status.md` §3 for why, and what that
does and doesn't confirm). A few things worth knowing before treating this as more than a
portfolio piece:

- **Checkout is not one atomic transaction** and has a known stock-overselling race — see
  `docs/project_status.md` §4.1. Ticket issuance would inherit the same bug if wired on top of it
  as-is.
- **The lottery draw job doesn't exist yet** — the schema supports it, nothing runs it.
- **The rate limiter's key doesn't include the route**, so endpoints sharing a `key_func` share
  one Redis budget.
- **Payment webhook handling isn't idempotent** (harmless today, would double-mint a ticket later).

Full list, ordered by how much each matters: `docs/project_status.md` §4.

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
Fill in `.env` — at minimum a JWT secret, and SendGrid/Razorpay keys if you want those flows to
work end to end (the app runs locally without valid third-party keys, but email sending and real
payments won't).

### 2. Start the stack
```bash
docker compose up --build
```
This starts the FastAPI app, PostgreSQL, and Redis, and runs `alembic upgrade head` on boot.

### 3. Explore the API
```
http://localhost:8000/docs
```

### 4. (Optional) Seed sample data
```bash
docker compose exec app python seed.py
```
Populates a full fictional roster — management companies, idol groups, venues, concerts, ticket
types, and marketplace products. Idempotent — safe to re-run.

### 5. Run tests
```bash
docker compose exec app pytest --cov=app
```

### 6. Stop the stack
```bash
docker compose stop
```
Keeps database data intact.

---

## License

No license file yet — all rights reserved by default until one is added.
