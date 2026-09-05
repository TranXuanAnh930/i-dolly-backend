# CLAUDE.md

Entry point for Claude (and anyone else) working in this repository. Keep this file short and
current — it's a map to the `docs/` folder, not a duplicate of what's in there. If a detail
here and a detail in `docs/` disagree, `docs/` wins; fix this file to match.

## 1. Context

An idol-concert **ticket reservation site** with an **album/singles marketplace**, built as a
**portfolio project** — not a real company's backend. It started as a generic FastAPI
e-commerce boilerplate (`VinayParmar555/E-commerce`, forked) and is being turned, incrementally,
into the idol-ticket domain: idols/groups, venues/concerts, lottery-based ticket sales, and an
album/lightstick marketplace layered on the original cart/order/payment plumbing.

## 2. Goal

To **showcase backend engineering skills** to whoever reviews this portfolio: schema design,
layered API architecture, migration discipline, auth/RBAC, and (planned, not yet built) a real
ETL/data pipeline. Optimize for a codebase that reads as deliberately designed and honestly
documented — including what's unfinished — over one that looks superficially complete.

## 3. Tech stack

FastAPI + Pydantic v2, PostgreSQL via SQLAlchemy 2.0 + Alembic, Redis (caching + rate limiting),
JWT auth, a mock payment gateway (real gateway integration is next-phase work), SendGrid,
a local/S3 image-storage abstraction, Docker
Compose for local dev. Full detail, versions, and reasoning: **`docs/architecture.md`** §1.

## 4. Domains

Four clusters — see `docs/database-design.md` §1 for the full breakdown:

- **Identity** — role-based access (`admin` / `manager` / `fan`), company-scoped managers.
- **Talent** — management companies, groups, idols, idol colors, positions.
- **Events & ticketing** — venues, concerts, ticket types (lottery or direct sale), lottery
  preferences/campaigns/entries, issued tickets.
- **Marketplace** — products/categories extended with album/single/EP details, lightstick
  details, genres — reusing the original cart/order/payment/shipping machinery.

## 5. Database & architecture

Don't re-derive these from the code — read the docs first, they're kept current:

- **`docs/database-design.md`** — the schema itself: ERD, table-by-table notes, the RBAC matrix,
  the lottery business logic as a sequence diagram, and a running log of resolved/open design
  questions. Read this before touching `Idol`, `Concert`, `Venue`, `TicketType`, or any lottery
  table.
- **`docs/architecture.md`** — how the code is organized: the router → service → model layering,
  error-handling conventions, cross-cutting deps (auth, rate limiting, image storage), migration
  conventions, and the specific conventions new code must follow (e.g. which module `Base` gets
  imported from).
- **`docs/project_status.md`** — what's actually built vs. still open, known issues/tech debt,
  and the verification method used so far (static analysis, not a live DB — see its §3 for why).
  Read this before assuming a feature exists or is finished.
- **`docs/deployment.md`** — how to actually deploy this: Render (API), Supabase (Postgres), an
  S3-compatible bucket (image uploads), and Render's Key Value add-on (Redis). Read this before
  touching env-var handling, CORS, or storage/cache backend selection.

## 6. Coding style

- Follow the existing three-layer split (router / service / model+schema) — see
  `docs/architecture.md` §2. Don't put ORM queries in routers or FastAPI imports in services.
- Match whichever error-handling convention (sentinel return vs. exception) the file you're
  touching already uses; don't introduce a third pattern into an existing service.
- Every new mutating/user-scoped query filters by `user_id` or `company_id` at the query level.
- One concern per Alembic migration; enum types use the atomic idempotent `DO $$ ... EXCEPTION
  WHEN duplicate_object ...` pattern, not `checkfirst=True` (`docs/architecture.md` §4 has why).
- New model files import `Base` from `app.db.base_class`, never `app.db.base`
  (`docs/architecture.md` §5 — this is a real circular-import trap, not a style nitpick).
- Comment code the way the rest of this repo does when a decision isn't obvious from the code
  alone — a one-line "why," not a restatement of what the line does.

## 7. Scope control

This is a portfolio project, not a production system — resist scope creep in both directions:

- **Don't gold-plate**: no real seat maps (capacity-based ticket tiers are the deliberate,
  confirmed design — `docs/database-design.md`'s intro), no real payment gateway required for
  local dev (the mock gateway is intentional), no premature multi-region/scaling work.
- **Don't skip the parts that demonstrate the skill the project is for**: migration discipline,
  RBAC/company-scoping, atomic transactions where money or inventory is at stake, and the ETL
  pipeline once the OLTP domain settles (`docs/project_status.md` §5) all matter more here than
  in a throwaway CRUD app, precisely because showcasing them is the point.
- When a request is ambiguous between "quick portfolio demo" and "production-grade," default to
  the more defensible, more clearly-reasoned choice and say so — don't silently pick the
  shortcut.
- Don't invent scope that hasn't been asked for (e.g. product "personality"/theming,
  `docs/project_status.md` §5) — flag it as open instead of designing it speculatively.

## 8. Claude rules

For any non-trivial change: **understand → plan → implement → verify → report.**

- **Understand**: read the relevant `docs/` file(s) and the specific code being touched before
  proposing a change — don't guess at existing conventions.
- **Plan**: for anything spanning more than one file, or any schema change, state the plan (even
  briefly) before writing code — especially migration sequencing, which is easy to get wrong
  given FK dependencies.
- **Implement**: follow the conventions in §6, not just "whatever compiles."
- **Verify**: at minimum, a `py_compile` sweep. Where a live DB/app isn't reachable, use the
  AST-based static checks described in `docs/project_status.md` §3 and say plainly that this is a
  substitute for real verification, not equivalent to it — never imply something was tested
  end-to-end when it wasn't.
- **Report**: summarize what changed and, just as importantly, what's now a known limitation or
  a deferred item — update `docs/project_status.md` when a feature actually lands or a known
  issue gets fixed, so it doesn't silently drift out of date.

## 9. Context management

Don't assume this conversation's history is permanent — a new session starts with none of it.

- **At the start of a new session, read this file first**, then only the specific `docs/` file(s)
  and source files the task actually needs. Don't read the whole repo "to be safe" — it's slow,
  expensive, and `docs/` exists specifically so that isn't necessary.
- If something here or in `docs/` looks stale relative to the actual code, trust the code, fix
  the doc, and move on — don't silently work around a stale doc without correcting it for the
  next session.
- Prefer updating `docs/project_status.md` over letting status live only in conversation —
  anything a future session (or a human reviewer) would need to know to avoid redoing work or
  reintroducing a fixed bug belongs there, not just in this chat.
