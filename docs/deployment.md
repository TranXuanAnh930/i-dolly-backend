# Deployment — Render (API) + Supabase (Postgres) + Render Key Value (Redis)

How to take this repo from local Docker Compose to a live deployment: API on Render, database on
Supabase, cache/rate-limiter on Render's own Redis-compatible add-on, and image uploads on
S3-compatible object storage. Read `project_status.md` §3 before starting — every migration in
this repo has been verified with `py_compile`/AST checks only, never against a real Postgres
instance, so **this deploy is also the first real test of `alembic upgrade head` end to end.**
Budget time for that specifically; see §7's rollback note.

## 0. Accounts you'll need

- [Render](https://render.com) — hosts the API and (per the storage/Redis choices below) the
  cache.
- [Supabase](https://supabase.com) — hosts Postgres.
- An S3-compatible object storage account for idol/product image uploads — AWS S3, Cloudflare R2,
  or DigitalOcean Spaces all work unchanged (`app/utils/storage.py` already supports all three via
  env vars, no code change). Cloudflare R2 has the most generous free tier if you don't already
  have a preference.
- A real Resend account is **not** required to deploy — `app/config/settings.py` requires
  `RESEND_API_KEY`/`FROM_EMAIL` to be *set* (Pydantic will refuse to boot otherwise) but nothing
  forces them to be valid unless you actually exercise the email-sending code paths. A placeholder
  value is fine for a portfolio deploy; see the table in §6. Payments use a mock gateway only —
  real payment gateway integration is deferred to a later phase, so there's nothing to configure
  there at all.

## 1. Code changes this deploy needed (already done)

Two things in this repo were hardcoded to local-dev assumptions and would have silently broken a
real deploy — both are already fixed as of this doc:

- **CORS** (`main.py`) — was a hardcoded `["http://localhost:8080"]`. Now reads a `CORS_ORIGINS`
  env var (comma-separated origins), defaulting to the same value so local dev is unaffected. Set
  this to your real frontend's origin(s) in Render (§6).
- **Email verification link** (`app/services/identity/auth_service.py`) — was hardcoded to a specific old
  Render domain from before this project was renamed. Now reads `BASE_URL` (§6).

Nothing else needs code changes to deploy — `Dockerfile` already runs `alembic upgrade head` then
`uvicorn main:app --host 0.0.0.0 --port $PORT` on boot, and `$PORT` is exactly the env var Render
injects into every web service automatically.

## 2. Supabase — Postgres

1. Create a new Supabase project (pick a region close to where you'll deploy the Render service —
   cross-region DB round-trips add real latency to every request).
2. **Settings → Database → Connection string.** Supabase gives you several variants — use the
   **Session pooler** connection string (port `6543` or `5432` depending on Supabase's current
   naming), not the raw direct connection. Two reasons:
   - Supabase's direct connection is IPv6-only on new projects unless you pay for the IPv4
     add-on; Render's outbound network may not route IPv6, and the failure mode (connection
     just hangs/times out) is confusing to debug blind. The pooler is IPv4-reachable.
   - This app is a long-lived server process with its own SQLAlchemy connection pool
     (`app/db/session.py`'s `create_engine(..., pool_pre_ping=True)`, default pool size), not a
     serverless function — so prefer **Session mode** over **Transaction mode** pooling if
     Supabase asks you to choose: transaction-mode pgbouncer doesn't support session-level
     features SQLAlchemy may rely on (e.g. prepared statements), session-mode does.
3. Copy that connection string — it's your `DATABASE_URL` (§6). It already includes
   `sslmode=require`; don't strip it.
4. You do **not** need to run any SQL by hand — the Dockerfile's `alembic upgrade head` on first
   boot creates every table, trigger, and enum type from the 40 migrations in `alembic/versions/`.

## 3. Object storage (S3-compatible) — for durable image uploads

Local disk storage (`STORAGE_BACKEND=local`) doesn't survive a Render redeploy — the filesystem is
ephemeral. Since durability was the chosen option here:

1. Create a bucket in your chosen provider (S3 / R2 / Spaces).
2. Make it public-read for the `idols/` and `products/` prefixes (or front it with a CDN and set
   `S3_PUBLIC_URL_BASE` — see below) — uploaded images need to be fetchable by a browser without
   auth, same as the local-disk path today.
3. Create an access key scoped to just that bucket (not a full-account key).
4. Set these env vars in Render (§6): `STORAGE_BACKEND=s3`, `S3_BUCKET_NAME`, `S3_REGION`,
   `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and — only for R2/Spaces (skip for real AWS S3) —
   `S3_ENDPOINT_URL` pointing at your provider's S3-compatible endpoint. No code changes needed;
   `app/utils/storage.py` already branches on `STORAGE_BACKEND`.

## 4. Redis — Render's Key Value add-on

1. In the Render dashboard, create a new **Key Value** (Render's current name for its
   Redis-compatible offering) instance in the **same region** as the web service you're about to
   create in §5 — same-region matters here, not just for latency: it's what makes the free
   *internal* connection available.
2. Use its **Internal Connection** details (a private hostname + port reachable only from other
   Render services in the same region), not the external one. Render's internal network doesn't
   require TLS or a password for this, which matters because **`app/cache/redis_client.py` only
   connects with `host`/`port`/`db` today — it has no password or TLS support.** If you ever move
   Redis off-Render (Upstash, etc.) or need the external connection string, that's a small code
   addition (`password=`, `ssl=True` on the `redis.Redis(...)` call) not present yet.
3. Set `REDIS_HOST` to the internal hostname, `REDIS_PORT` to its port (usually `6379`), `REDIS_DB`
   to `0`.

## 5. Render — the Celery worker (needed now that a real task exists)

`app/celery_app.py` has a real task now — the manager-triggered lottery draw
(`app.tasks.lottery.draw_lottery`, `docs/project_status.md` §8) — so this section is no longer
skippable the way it was when it was a bare skeleton. No Celery Beat/scheduler is used: every
notification producer (`docs/project_status.md` §2) fires inline, inside the request/task that
causes it, not on a cron — so only the worker needs deploying, not a second scheduler process.

1. **New → Background Worker** (not Web Service), same repo, same `Dockerfile`.
2. **Start Command**: `/start-worker.sh` (overrides the image's default `CMD`, which is the web
   service's `/start.sh`).
3. Same region as the Key Value instance from §4, for the internal Redis connection.
4. Env vars: the same `DATABASE_URL`/`REDIS_HOST`/`REDIS_PORT`/`REDIS_DB` as the web service (§6)
   — `CELERY_BROKER_DB` defaults to `1` and doesn't need to be set unless you want a different
   index. No migration step here; the web service's boot already runs `alembic upgrade head`
   against the same database.

## 6. Render — the web service

1. **New → Web Service**, connect the `TranXuanAnh930/i-dolly-backend` GitHub repo.
2. **Runtime: Docker.** Render will build from the repo's `Dockerfile` directly — no build/start
   command needed, the Dockerfile's own `CMD ["/start.sh"]` handles both `alembic upgrade head`
   and starting `uvicorn`.
3. Region: same as the Key Value instance from §4 (for the internal Redis connection to work) and
   as close as practical to your Supabase region.
4. Instance type: the free tier works for a portfolio demo, but note Render's free web services
   spin down after inactivity and cold-start slowly — fine for a resume link, mention it if anyone
   is timing first-load latency.
5. Add every env var from the table in §7, then create the service. The first deploy will build
   the image, run migrations, and start the app — watch the deploy logs for the migration step
   specifically (§8).

## 7. Environment variables — full checklist

| Variable | Value | Notes |
|---|---|---|
| `DATABASE_URL` | Supabase session-pooler connection string (§2) | |
| `DATABASE_NAME` / `DATABASE_USER` / `DATABASE_PWD` | any non-empty values, e.g. copied from the Supabase connection string | Required by `app/config/settings.py`'s schema but **not actually read anywhere in `app/`** — vestigial from the original docker-compose-only setup. Set them so the app boots; not worth a code change just for this. |
| `JWT_SECRET_KEY` / `JWT_REFRESH_SECRET_KEY` / `JWT_EMAIL_SECRET_KEY` | three distinct random secrets | Generate with `python -c "import secrets; print(secrets.token_hex(32))"`, once each |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | matches `.env.example` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | |
| `EMAIL_TOKEN_EXPIRE_MINUTES` | `60` | |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` | from §4 | internal hostname, usually `6379`, `0` |
| `CELERY_BROKER_DB` | `1` (default, can be omitted) | only relevant if the Celery worker (§5) is deployed too |
| `RESEND_API_KEY` / `FROM_EMAIL` | real key, or a placeholder | only exercised by the email-verification/password-reset flows |
| `DEBUG` | **omit, or `false`** | dev-only: prints verification/reset tokens to the console when a placeholder `RESEND_API_KEY` can't actually deliver (`architecture.md`'s Resend note). Leaving it unset defaults to `false`, which is what you want here — these token bodies have no business in Render's shared logs. |
| `BASE_URL` | `https://<your-render-service>.onrender.com` | used to build the email verification link |
| `CORS_ORIGINS` | your frontend's real origin(s), comma-separated | e.g. `https://your-frontend.vercel.app` |
| `STORAGE_BACKEND` | `s3` | per the chosen option in §3 |
| `S3_BUCKET_NAME` / `S3_REGION` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | from §3 | |
| `S3_ENDPOINT_URL` | your provider's endpoint | **omit for real AWS S3**, required for R2/Spaces |
| `S3_PUBLIC_URL_BASE` | optional CDN/custom domain | falls back to a computed bucket URL if unset |

## 8. First deploy — migrations are the real risk here

Watch the Render deploy log for the `Running Alembic migrations...` line the Dockerfile prints.
This is the very first time these 40 migrations — including the UUID primary-key rewrite and all
12 trigger functions — will run against a real Postgres. If it fails partway through:

- Render's log will show which revision failed and the raw Postgres error.
- Fix forward: correct the migration file, commit, and let Render redeploy — don't hand-edit
  Supabase's schema directly, or the migration history and the live schema will drift apart.
- If a migration partially applied before failing (e.g. a `CREATE TABLE` succeeded but a
  subsequent `CREATE TRIGGER` in the same file didn't), you may need to manually drop what that
  one migration created in the Supabase SQL editor before retrying — Alembic doesn't
  auto-rollback a failed migration's own DDL within Postgres's transactional DDL, but multiple
  `op.execute()` calls in one `upgrade()` aren't automatically one atomic unit either. Cross this
  bridge only if it actually happens; don't pre-solve it speculatively.

## 9. Wire up CI/CD auto-deploy (optional, already scaffolded)

`.github/workflows/test.yml` already has a `deploy` job that `curl`s a `RENDER_DEPLOY_HOOK` secret
on every push to `main` after tests pass — this was set up for the original fork's Render service,
so the secret needs to be re-added for this repo:

1. In the new Render service's **Settings → Deploy Hook**, copy the deploy hook URL.
2. In `TranXuanAnh930/i-dolly-backend`'s GitHub repo **Settings → Secrets and variables → Actions**,
   add `RENDER_DEPLOY_HOOK` with that URL. The workflow's other secrets (`JWT_SECRET_KEY`, etc.)
   are only used by the *test* job against the CI Postgres/Redis services, not the real deploy —
   they don't need to match your Render env vars.

## 10. Post-deploy smoke test

1. `https://<your-service>.onrender.com/docs` — Swagger UI should load.
2. `POST /account/register` → `POST /account/login` — confirms the DB connection and JWT flow.
3. `GET /products/all` — confirms Redis (product-list cache) is reachable.
4. If you seed data: `render shell` into the service (or a one-off Render job) and run
   `python scripts/seed.py` — it's idempotent, safe to run once against the fresh Supabase DB.

## 11. Known limitations carried into this deploy

- No live-DB verification has happened before this deploy (§8) — treat the first deploy as a real
  test, not a formality.
- The Celery worker (§5) now backs a real task (the manager-triggered lottery draw) — deploying it
  is no longer optional the way it was when it was a bare skeleton; skipping it means
  `PUT /concerts/lottery-draw/{id}` returns "scheduled" but the draw never actually runs.
- The checkout/ticket-inventory race and non-idempotent webhook handling
  (`docs/project_status.md` §4 items 1 and 4) are unchanged by deploying — they're app-logic bugs,
  not deploy-environment issues.
- Render's free tier cold-starts after inactivity; if that matters for a demo, mention it rather
  than let a slow first load look like a bug.
