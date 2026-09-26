# Fix plan: trustworthy client IPs for rate limiting (bugs.md #7)

**Status:** planned, not started (2026-09-26).

## Problem

`ip_key` keys limits on `request.client.host`. `ProxyHeadersMiddleware(trusted_hosts="*")` sets that
from the **leftmost** `X-Forwarded-For` entry, which the client writes; Render appends the real IP on
the right. Rotating a fake leftmost entry bypasses every IP limit (login, register, forgot-password,
set-password, verify). Reproduced with TestClient: 30 wrong-password logins with a spoofed header →
0 × 429 (same IP without spoofing → 20 × 429).

Removing the middleware isn't the answer either: then every visitor shares Render's proxy IP, so one
bucket rate-limits everyone. The client IP has to be read from the right, skipping only our proxies.

## Steps

0. **Measure the hop count on Render.** Temporarily log
   `request.headers.getlist("x-forwarded-for")` and `request.client.host`, deploy, then
   `curl -H "X-Forwarded-For: 1.2.3.4" https://<render-url>/`. The number of entries after `1.2.3.4`
   is **N** (trusted proxy hops); the real IP is at position `-N`. Remove the log line.
1. **Setting:** `TRUSTED_PROXY_HOPS: int = 0` in `app/config/settings.py` (0 = no proxy, ignore the
   header). Set it to N on Render (`render.yaml`, `docs/deployment.md`).
2. **`client_ip(request)` in `app/cache/rate_limit.py`**, used by `ip_key`:
   - hops == 0 → `request.client.host`.
   - Otherwise combine every `X-Forwarded-For` header (`getlist`, split on commas), take
     `entries[-hops]`.
   - Fall back to the peer address if the list is shorter than `hops` or the entry isn't a valid IP
     (`ipaddress.ip_address`).
3. **Remove `ProxyHeadersMiddleware`** from `main.py` so one function owns "what's the client IP".
   First grep for `request.url` / `url_for` to confirm nothing relies on its `X-Forwarded-Proto`
   handling (links are built from `settings.BASE_URL`).
4. **Per-account limit on failed logins** (IP limits can't stop an attacker with many real IPs):
   - Key `rate:login_fail:{email.lower()}`, e.g. 5 failures / 15 min.
   - In the `login` router: over the limit → 429 with a generic message (don't reveal whether the
     account exists); on failure, increment with the expiry set atomically (pipeline or
     `SET … NX EX`, see bugs.md #22); optionally clear on success.
   - Same idea for forgot-password keyed by email (e.g. 3 / hour).
   - Helpers `record_login_failure(email)` / `login_attempts_exceeded(email)` in `rate_limit.py`.
5. **Tests:**
   - Unit, `client_ip`: hops 0 ignores the header; hops 1 `fake, real` → real; hops 2
     `fake, real, cdn` → real; several headers combined; short list / invalid IP → peer.
   - Regression: `TRUSTED_PROXY_HOPS=1`, 11 logins with a different fake leftmost entry and the same
     real right-hand IP → the 11th is 429.
   - Per-account: 6 failures for one email from 6 different IPs → the 6th is 429; another email still
     works.
6. **Docs:** bugs.md #7 (and #22 if fixed alongside), `deployment.md` (`TRUSTED_PROXY_HOPS` + the
   step 0 check), `architecture.md` §3 (rate limiting keyed by `client_ip()` plus per-account
   limits).
7. **Production check:** ~12 login requests with a fake `X-Forwarded-For` → 429s.

## Choosing N

Too high → trusts a client-written entry (this bug). Too low → everyone shares the proxy's bucket
(the original problem). Measure it (step 0); don't assume.

**Files:** `app/config/settings.py`, `app/cache/rate_limit.py`, `main.py`,
`app/router/identity/auth.py` (+ `user.py` for forgot-password), new unit/integration tests,
`render.yaml`, `docs/deployment.md`, `docs/architecture.md`, `docs/bugs.md`.
