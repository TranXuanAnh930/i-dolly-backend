# API Endpoint Spec — Frontend Integration Guide

Companion to `../CLAUDE.md`, `architecture.md`, `database-design.md`, and `project_status.md`
(same `docs/` folder). Those explain the system; this file is the handoff surface — every route
the backend exposes today, grouped by the page a frontend would use it from, so a UI can be built
against a page inventory and then wired to real endpoints one section at a time.

Generated from the live route/schema definitions in `app/router/` and `app/schema/` (not hand
transcribed), so method/path/param names below match the code exactly. Response *shapes* for
endpoints that declare a `response_model` are Pydantic-enforced and reliable. A few endpoints
return a plain dict or ORM object with no `response_model` (noted per-endpoint below) — their
shape is documented from the actual `return` statement in the service/router, but FastAPI isn't
enforcing it, so treat those as "best current description," not a contract. Routes marked
"Not used by the frontend" carry that comment in the router source too.

## 0. Conventions

**Base URL.** No global prefix — every path below is mounted at the app root (`main.py` does
`app.include_router(...)` with no `prefix=`). Interactive docs are served at `/docs` (Swagger UI,
auto-generated from the same route definitions) and `/redoc` — useful for exploring exact schemas
live once a server is running, this file is for planning UI against before/without one.

**Auth.** JWT bearer tokens. Obtain one via `POST /account/login` (see §1) and send it as
`Authorization: Bearer <access_token>` on every endpoint marked 🔒 below — the frontend owns storing
and attaching the access token. The **refresh token** is different: login and `/account/refresh`
set it as an `httponly; secure; samesite=none` cookie named `refresh_token`, so the frontend never
sees it and must call `/account/refresh` with credentials included (`fetch(..., {credentials:
"include"})` / `withCredentials`) to rotate it. A request to a 🔒 endpoint with a
missing/invalid/expired token gets `401`; a valid token but wrong role gets `403` (see role
legend). `require_manager_or_admin` only checks *role*, not company ownership — several services
additionally 403 when a manager acts outside their own company's resources (noted per-endpoint as
"company-scoped").

**Role legend** (from `app/deps/auth.py`, checked against `Users.role`):
- 🔓 — no auth required (public)
- 🔒 fan — any authenticated user (`get_current_user`); no role restriction beyond being logged in
- 🔒 manager+ — `require_manager_or_admin`: role is `manager` or `admin`
- 🔒 admin — `require_admin`: role is `admin` only

**Error shape.** Every error body is `{"detail": ..., "code": "<snake_case>"}`.
- `detail` is a human-readable English string — except for a `422` from request validation, where
  it's FastAPI's list of `{loc, msg, type}` field errors. Show it as secondary text at most; don't
  parse it.
- `code` is stable: branch on it (and translate it) in the UI. Unlisted codes may be added later —
  fall back to the status code.

| Code | Status | When |
|---|---|---|
| `not_authenticated` | 401 | Missing, invalid or expired access token, or its user no longer exists |
| `invalid_credentials` | 401 | `POST /account/login`: wrong email or password |
| `invalid_refresh_token` | 401 | `POST /account/refresh`: cookie missing, expired or revoked |
| `invalid_token` | 400 / 401 | Email-verification link (400) or password-reset token (401) invalid or expired |
| `incorrect_password` | 400 | `PUT /profile/change-password`: old password wrong |
| `email_taken` | 400 | Register / create manager with an existing email |
| `already_verified` | 409 | `GET /account/verify` on a verified account |
| `forbidden` | 403 | Wrong role, or a manager acting outside their company |
| `fan_only_purchase` | 403 | A manager or admin tried to buy, add to cart or enter a lottery |
| `not_found` | 404 | The requested resource doesn't exist (or isn't the caller's) |
| `validation_error` | 422 | Request body/query/path failed validation |
| `rate_limited` | 429 | Too many requests; `detail` says how many seconds to wait |
| `method_not_allowed` | 405 | Wrong HTTP method |
| `internal_error` | 500 | Unexpected server error (logged server-side); safe to retry reads |
| `invalid_image` | 400 | Image upload rejected: unsupported type, over 5 MB, or storage misconfigured |
| `insufficient_stock` | 400 | Cart add or order checkout: not enough stock |
| `cart_empty` | 404 | `POST /order/checkout` with an empty cart |
| `address_not_found` | 404 | Checkout with an unknown shipping address |
| `amount_mismatch` | 400 | Checkout `amount` doesn't match the current total (prices changed — refetch) |
| `unsupported_gateway` | 400 | Unknown `gateway` value |
| `resale_cap_exceeded` | 400 | More than 3 units of one product per fan |
| `duplicate_idempotency_key` | 409 | Checkout retried with an already-used `idempotency_key` (a double submit) |
| `ticket_type_not_found` | 404 | `POST /tickets/checkout` with an unknown ticket type |
| `wrong_sale_method` | 400 | Buying a lottery tier directly, or ranking a direct-sale tier |
| `not_on_sale` | 400 | No open direct-sale campaign covers now |
| `sold_out` | 400 | No seats left in the tier |
| `duplicate_concert_ticket` | 400 | The fan already holds a live ticket for this concert |
| `lottery_entry_unresolved` | 400 | Direct purchase blocked by a pending or won lottery entry for the concert |
| `ticket_not_found` | 404 | Paying for a won ticket that doesn't exist or isn't the caller's |
| `ticket_not_payable` | 400 | The ticket isn't an unpaid lottery win |
| `payment_deadline_passed` | 400 | The lottery win's payment deadline passed; the ticket is now expired |
| `ranking_locked` | 400 | Changing lottery rankings after entries closed |
| `no_lottery_campaign` | 404 | Ranking a tier that has no lottery campaign |
| `entries_not_open` | 400 | Ranking or applying before the entry window opens |
| `entries_closed` | 400 | Applying after the entry window closed |
| `campaign_not_open` | 400 | Applying to a campaign that's already drawn |
| `campaign_cancelled` | 400 | Applying to a cancelled campaign |
| `tier_already_applied` | 400 | Removing a ranked tier the fan has already applied to |
| `duplicate_ranked_tier` | 400 | The same tier twice in one ranking |
| `lottery_preference_required` | 400 | Applying to a tier the fan hasn't ranked |
| `lottery_entry_cap_exceeded` | 400 | Already applied to this campaign |
| `no_open_campaigns` / `entries_not_ended` | 400 | Lottery draw triggered too early, or with nothing to draw (manager) |
| `order_already_shipped` / `order_cancelled` / `invalid_shipping_transition` | 400 | Order cancel / shipping-status changes not allowed from the current status (manager/admin) |
| `bad_request` / `conflict` / `rule_violation` | 400 / 409 / 400 | Generic fallbacks, mostly manager/admin form checks — show `detail` |
| other trigger codes | 400 | `ticket_type_concert_mismatch`, `product_detail_kind_conflict`, `concert_capacity_exceeded`, `duplicate_ticket_type` (manager/admin forms) |

**Empty results are never errors.** Every list endpoint returns `200 []` when there's nothing to
list, and the page endpoints (`/products/store-page`, `/concerts/events-page`, `/idols/members-page`,
`/groups/groups-page`) return their object with empty lists. `GET /cart/see_cart` on an empty cart
returns `{"items": [], "total_price": 0}`. `404` always means a specific resource is missing.

Payment outcomes that aren't errors: a declined mock payment returns **200** with the order's or
ticket's `status: "cancelled"`; a PayPal checkout returns **200** with `status: "pending"`.

A handful of endpoints return `{"msg": "<message>"}` on success for simple actions (deletes,
password changes) instead of the resource itself — called out per-endpoint below since it affects
whether the frontend can optimistically update from the response or must refetch.

**Pagination.** A few endpoints take `page`/`limit` query params and return
`{"page", "limit", "count", "data"}`: `GET /products/pagination`, `GET /products/filter`, and the
manager-side `GET /order/manager-orders-page`, `GET /products/{id}/sales`,
`GET /tickets/concert/{id}/sales`. `count` is the size of the returned page, not the total
(`docs/bugs.md` #23), so there's no reliable "last page" signal yet — stop when a page comes back
short. Every other list endpoint returns the full collection unpaginated.

**Page endpoints.** Many screens have one `*-page` or `/{id}/detail` endpoint that returns
everything the page needs in one response (e.g. `GET /products/store-page`,
`GET /concerts/{id}/detail`). They're Redis-cached (5-minute TTL, invalidated on writes), so
prefer them over stitching together the per-resource CRUD reads below. The `manager-*-page`
reads are currently **unauthenticated** and not company-scoped server-side (`docs/bugs.md` #29) —
the frontend filters by the manager's company.

**Image uploads.** `POST /idols/add` and `POST /products/add_product` are `multipart/form-data`,
not JSON — every other write endpoint on this list is JSON. See §3 (`Idols`) and §5 (`Products`)
for the exact form fields. Uploaded images are served back from whatever `LOCAL_UPLOAD_URL_PREFIX`
resolves to (default `/uploads/...`) or a real S3/CDN URL, depending on backend deploy config —
either way, `image_url`/`profile_image_url` in the response is a ready-to-use `<img src>`.

**Rate limits.** Most endpoints are rate-limited per-IP or per-user by a tier policy
(`architecture.md` §3): auth and money/inventory writes are tight (3–10/min), polled reads are
loose (up to 60/min). A `429` means back off, not a bug; its `detail` says how many seconds to wait.
Not exhaustively listed below — see the `rate_limit(...)` dependency on each route if a specific
limit matters to a retry/backoff strategy.

## 1. Suggested frontend page structure

A starting page inventory, grouped by who uses it, with the endpoint sections each pulls from.
Not prescriptive — just a shape that maps cleanly onto what the backend actually supports today,
so a UI can be scaffolded before every endpoint is wired in.

**Public (no login):**
- Home / landing — highlights across idols, groups, upcoming concerts (§3, §4)
- Members page / idol profile — `GET /idols/members-page`, `GET /idols/{id}/detail` (§3)
- Groups page / group profile — `GET /groups/groups-page`, `GET /groups/{id}/detail` (§3)
- Events page / concert detail — `GET /concerts/events-page`, `GET /concerts/{id}/detail` (§4;
  the detail page also carries the signed-in fan's own ticket/lottery state)
- Store + product detail — `GET /products/store-page`, `GET /products/{id}/detail` (§5)
- Contact page — §8 `Inquiries` (instant FAQ answer, then the form)
- Login / register / email verify / forgot-password / reset-password — §2

**Fan (logged in, any role):**
- My profile — §2 `Profile`
- Cart — §6 `Cart`
- Checkout — §6 `Order` (`/checkout`), `Shipping Addresses`, `Payment`
- My orders (list + detail + cancel + shipping status) — §6 `Order`
- My payment status — §6 `Payment`
- My tickets — §4 `Tickets` (`/mine`)
- Lottery: apply to a campaign, rank ticket-type preferences, see my entries, pay for a won
  ticket — §4 `Lottery Campaigns`, `Lottery Preferences`, `Lottery Entries`, `Tickets`
- Direct-sale ticket purchase — §4 `Tickets` (`/checkout`), while a direct-sale campaign is open
- Notifications — §7

**Manager (their own company's idols/groups/concerts/products):**
- Manager dashboard — entry point into the sections below, scoped to their `company_id`
- Manage idols / groups / positions / idol colors — §3 (create/edit; delete on colors is
  admin-only)
- Manage concerts, ticket types, performer assignments, lottery and direct-sale campaigns — §4;
  trigger a concert's lottery draw (`PUT /concerts/lottery-draw/{id}`) and view the results
- Orders to ship — `GET /order/manager-orders-page`, `PATCH /order/{order_id}/ship` (§6)
- Manage products, album details, merch details, genre assignments — §5 (product image
  upload/replace, update, delete are company-scoped — see the 403 note under `Products`)

**Admin (site-wide):**
- Manage management companies — §2 `Management Companies`
- Manage categories, genres (delete), venues — §5, §4
- Promote a user to admin — §2 `Profile` (`/make-admin`)
- Manually issue / edit / delete tickets — §4 `Tickets` (a support/testing tool; normal tickets
  come from the lottery draw or direct-sale checkout)
- Update an order's shipping status — §6 `Order` (`/update_shipping_status`)
- Delete any idol color / genre / position / venue / management company — admin-only across the
  board even where manager+ can create/update (see role column per section)

---

## 2. Account & Profile

### `POST /account/register` 🔓
Create a new user account (role defaults to `fan` — nothing here lets a caller self-assign
`manager`/`admin`).
- Request (JSON — `UserCreate`): `name` (str), `email` (str, validated email), `password` (str,
  6–128 chars)
- Response (`UserOut`): `id`, `name`, `email`, `role` (`"admin"|"manager"|"fan"` — always `"fan"`
  here), `company_id` (uuid, nullable — always `null` here), `is_active`, `is_admin`,
  `is_verified`, `created_at`, `updated_at`
- UI: Register page

### `POST /account/login` 🔓
OAuth2 password grant — the token source for every 🔒 endpoint.
- Request: `application/x-www-form-urlencoded` (OAuth2 form, not JSON) — `username` (send the
  user's **email** in this field), `password`
- Response: not schema-enforced; standard token pair (`access_token`, `refresh_token`, `token_type`)
- UI: Login page. Rate-limited (10/min/IP).

### `POST /account/refresh` 🔓
Exchange a refresh token for a new access token.
- Request: reads the refresh token from the request (`Request` param, no declared body schema —
  check current cookie/body convention against `/docs` before wiring)
- Response: not schema-enforced; new token pair
- UI: silent background call on access-token expiry, not a user-facing screen

### `POST /account/verify-request` 🔒 fan
Send/resend the email-verification link to the current user.
- Request: none
- Response: not schema-enforced
- UI: "Resend verification email" button (e.g. on a "please verify your email" banner)

### `GET /account/verify` 🔓
Confirm an email via the token from the verification link.
- Request: query param `token` (str)
- Response: `{"msg": "Email verified successfully"}`
- Errors: `400` (invalid or expired token, or the token's user no longer exists), `409` (account
  already verified)
- UI: the landing page a verification-email link opens

### `GET /profile/me` 🔒 fan
- Response (`UserOut`): same shape as register's response — `role`/`company_id` now included, so
  the frontend can read `currentUser.role`/`currentUser.company_id` directly
- UI: profile page, header user menu

### `PUT /profile/change-password` 🔒 fan
- Request (`ChangePasswordRequest`): `old_password` (str), `new_password` (str, 6–128 chars)
- Response: `{"msg": "Password changed succesfully"}`
- UI: account settings

### `POST /profile/forgot-password` 🔓
- Request (`ForgotPasswordRequest`): `email`
- Response: `{"msg": "reset link sent successfully"}`
- UI: "Forgot password?" flow, step 1

### `POST /profile/set-password` 🔓
Complete a password reset using the token from the emailed link.
- Request (`SetPasswordRequest`): `token` (str), `new_password` (str, 6–128 chars)
- Response: `{"msg": "password changed successfully"}`
- UI: "Forgot password?" flow, step 2 (the link target)

### `POST /profile/make-admin` 🔒 admin
- Request (`MakeAdminRequest`): `user_id` (uuid)
- Response: `{"msg": "user <id> promoted to admin successfully"}`
- UI: admin user-management screen

### `POST /profile/create-manager` 🔒 admin
Creates a brand-new `role="manager"` account tied to a company in one call — distinct from
`/make-admin`, which only *promotes an existing user* and has no company concept. Use this for
"create a company user account" flows.
- Request (`ManagerCreate`): `name` (str), `email` (str, validated email), `password` (str,
  6–128 chars), `company_id` (uuid, must reference an existing management company)
- Response (`UserOut`): same shape as register's response — `role` is `"manager"`, `company_id`
  is the given company
- Errors: `400` (email already registered), `404` (company_id doesn't exist)
- UI: admin "create company user" screen

### `POST /profile/logout` 🔓
Invalidates the current refresh token.
- Request: none (reads from `Request`)
- Response: not schema-enforced
- UI: logout button

### `DELETE /profile/delete` 🔒 fan
Deletes the caller's own account.
- Response: `{"msg": "user <id> deleted successfully"}`
- UI: "Delete my account" in account settings, behind a confirmation

### `POST /management_companies/add` 🔒 admin
- Request (`ManagementCompanyCreate`): `name` (str), `description` (str, optional), `contact_email`
  (str, optional)
- Response (`ManagementCompanyRead`): adds `id`
- UI: admin — manage companies

### `GET /management_companies/all` 🔓
- Response: `List[ManagementCompanyRead]`
- UI: admin company list; also anywhere a manager-signup or idol/group form needs a company
  picker

### `GET /management_companies/{id}` 🔓
- Response: `ManagementCompanyRead`
- UI: company detail (admin)

### `PUT /management_companies/update/{id}` 🔒 admin
- Request (`ManagementCompanyBase`): `name`, `description`, `contact_email`
- Response: `ManagementCompanyRead`
- UI: admin — edit company

### `DELETE /management_companies/delete/{id}` 🔒 admin
- Response: `{"msg": "Management company deleted successfully"}`
- UI: admin — company list

---

## 3. Talent — Idols, Groups, Positions, Colors

### `POST /idol_colors/add` 🔒 manager+
Idol "brand color" (used for theming an idol's profile/lightstick — see `database-design.md`).
- Request (`IdolColorCreate`): `name` (str), `hex_code` (str, `^#[0-9A-Fa-f]{6}$`)
- Response (`IdolColorRead`): adds `id`
- UI: manager — color picker admin (usually a small reusable list, not its own page)

### `GET /idol_colors/all` 🔓
- Response: `List[IdolColorRead]`
- UI: color-select dropdown wherever an idol is created/edited

### `PUT /idol_colors/update/{id}` 🔒 manager+
- Request (`IdolColorBase`): `name`, `hex_code`
- UI: manager — edit color

### `DELETE /idol_colors/delete/{id}` 🔒 admin
- Response: `{"msg": "Idol color deleted successfully"}`
- UI: admin only, despite colors otherwise being manager-editable

### `POST /positions/add` 🔒 manager+
Position/role catalog (e.g. "Leader", "Main Vocalist") — shared across all groups, not
per-company.
- Request (`PositionCreate`): `name` (str)
- Response (`PositionRead`): adds `id`
- UI: manager — position catalog admin

### `GET /positions/all` 🔓
- Response: `List[PositionRead]`
- UI: position picker when assigning a member to a group

### `PUT /positions/update/{id}` 🔒 manager+
- Request (`PositionBase`): `name`

### `DELETE /positions/delete/{id}` 🔒 admin
- Response: `{"msg": "Position deleted successfully"}`

### `POST /positions/idol_positions/assign` 🔒 manager+
Assign a position to an idol.
- Request (`IdolPositionAssign`): `idol_id` (uuid), `position_id` (uuid), `is_primary` (bool,
  default `false`)
- Response (`IdolPositionRead`): `idol_id`, `position_id`, `is_primary`, nested `position`
  (`PositionRead`)
- UI: idol edit page — "roles" section

### `GET /positions/idol_positions/idol/{idol_id}` 🔓
- Response: `List[IdolPositionRead]`
- UI: idol profile page — role badges (e.g. "Main Vocalist")

### `GET /positions/idol_positions/all` 🔓
Not used by the frontend.
- Response: `List[IdolPositionRead]` (`idol_id`, `position_id`, `is_primary`, `position`)
- Errors: `404` if no idol has a position yet

### `PUT /positions/idol_positions/{idol_id}/{position_id}` 🔒 manager+
Toggle whether this position is the idol's primary one.
- Request: query/body param `is_primary` (bool) — no request schema, plain param
- Response (`IdolPositionRead`)
- UI: idol edit page — "set as primary role"

### `DELETE /positions/idol_positions/{idol_id}/{position_id}` 🔒 manager+
- Response: `{"msg": "Position unassigned from idol successfully"}`
- UI: idol edit page — remove a role

### `POST /groups/add` 🔒 manager+
- Request (`GroupCreate`): `name` (str), `debut_date` (date, optional), `description` (str,
  optional, ≤2000 chars), `company_id` (uuid)
- Response (`GroupRead`): adds `id`, `is_active` (always `true` on create), `created_at`, `updated_at`
- UI: manager — create group

### `GET /groups/all` 🔓
- Response: `List[GroupRead]` — **only `is_active=True` groups** (database-design.md §3.3)
- UI: group directory / home page carousel

### `GET /groups/{id}` 🔓
- Response: `GroupRead` — deliberately **not** filtered by `is_active`, so a manager's edit form
  can still load a deactivated group
- UI: group profile page, manager edit form

### `GET /groups/groups-page` 🔓
Everything the public groups page needs, cached.
- Response (`GroupsPageRead`): `groups` — each a `GroupRead` plus `member_count`
- Errors: `404` if there are no groups
- UI: public groups listing

### `GET /groups/{id}/detail` 🔓
- Response (`GroupDetailRead`): `group` (`GroupRead`), `members` (idols with positions, color and
  group), `events` (concerts with their venue), `products` (`ProductCard`s credited to the group)
- Errors: `404` if the group doesn't exist
- UI: group profile page

### `GET /groups/manager-groups-page` 🔓 (unauthenticated — see §0)
- Response (`ManagerGroupsPageRead`): `groups` (`List[GroupRead]`, every company's)
- UI: manager — groups table (filter to the manager's `company_id` client-side)

### `PUT /groups/update/{id}` 🔒 manager+ (company-scoped)
- Request (`GroupUpdate`): `name`, `debut_date`, `description` — `is_active` is **not** settable
  here; use the delete/activate endpoints below
- UI: manager — edit group

### `DELETE /groups/delete/{id}` 🔒 manager+ (company-scoped)
Soft delete — sets `is_active = false`, does not remove the row (database-design.md §3.3).
- Response: `{"msg": "Group deleted successfully"}`

### `PATCH /groups/activate/{id}` 🔒 manager+ (company-scoped)
Reverses the delete above — sets `is_active = true`.
- Response (`GroupRead`): full reactivated group
- UI: manager — settings page, "reactivate" on a deactivated group

### `POST /idols/add` 🔒 manager+ — **multipart/form-data**, not JSON
- Request (form fields): `name` (str, required), `company_id` (uuid, required), `group_id` (uuid,
  optional), `date_of_birth` (date, optional), `hometown` (str, optional), `color_id` (uuid,
  optional), `short_intro` (str, optional, ≤500 chars), `long_description` (str, optional),
  `image` (file, optional — max 5MB, `image/jpeg|png|webp|gif`)
- Response (`IdolRead`): all the above plus `id`, `is_active` (always `true` on create),
  `profile_image_url`, `created_at`, `updated_at`
- `400` if `group_id` names a deactivated group — new members can't be assigned into an inactive
  group (database-design.md §3.3)
- UI: manager — create idol (with photo upload in the same form)

### `GET /idols/all` 🔓
- Response: `List[IdolRead]` — **only `is_active=True` idols** (database-design.md §3.4)
- UI: idol directory / home page

### `GET /idols/{id}` 🔓
- Response: `IdolRead` — deliberately **not** filtered by `is_active`, so a manager's edit form
  can still load a deactivated idol
- UI: idol profile page, manager edit form

### `GET /idols/members-page` 🔓
- Response (`MembersPageRead`): `idols` (each with `idol_positions`, `color`, `group`), `groups`
  (`id`, `name` — for a filter control)
- Errors: `404` if there are no idols
- UI: public members page

### `GET /idols/{id}/detail` 🔓
- Response (`IdolDetailRead`): `idol` (with positions, color, group), `group` (`id`, `name`,
  `description`, or `null` for a solo idol), `siblings` (the other members of the same group)
- Errors: `404` if the idol doesn't exist
- UI: idol profile page

### `GET /idols/manager-idols-page` 🔓 (unauthenticated — see §0)
- Response (`ManagerIdolsPageRead`): `idols` (`List[IdolRead]`), `groups` (`id`, `name`)
- UI: manager — idols table

### `GET /idols/manager-idol-form-page` 🔓 (unauthenticated — see §0)
- Response (`ManagerIdolFormPageRead`): `idols`, `groups` (`id`, `name`, `company_id`,
  `is_active` — for the group picker), `colors` (`List[IdolColorRead]`)
- UI: manager — create/edit idol form

### `PUT /idols/update/{id}` 🔒 manager+ (company-scoped) — **JSON**, not multipart
Updates every field except the image — use the dedicated image endpoint below for that.
- Request (`IdolUpdate`): same fields as `IdolCreate` minus `company_id` (ownership is immutable)
  — `is_active` is **not** settable here; use the delete/activate endpoints below
- `400` if `group_id` names a deactivated group **and it's a genuine change** — resending the
  idol's current (already-deactivated) `group_id` unchanged is allowed, only moving an idol *into*
  an inactive group is rejected (database-design.md §3.3)
- UI: manager — edit idol (text fields)

### `DELETE /idols/delete/{id}` 🔒 manager+ (company-scoped)
Soft delete — sets `is_active = false`, does not remove the row (database-design.md §3.4).
- Response: `{"msg": "Idol deleted successfully"}`

### `PATCH /idols/activate/{id}` 🔒 manager+ (company-scoped)
Reverses the delete above — sets `is_active = true`.
- Response (`IdolRead`): full reactivated idol
- UI: manager — settings page, "reactivate" on a deactivated idol

### `POST /idols/{id}/image` 🔒 manager+ (company-scoped)
Replace an idol's photo only, without touching any other field.
- Request: `multipart/form-data`, `image` (file, required)
- Response (`IdolRead`): full updated idol
- UI: manager — edit idol, "change photo" control (separate from the main edit form's save)

---

## 4. Events & Ticketing

### `POST /venues/add` 🔒 admin
- Request (`VenueCreate`): `name`, `address`, `city`, `country` (all str, required), `total_capacity`
  (int, >0), `contact_info` (str, optional)
- Response (`VenueRead`): adds `id`, `size` (derived label), `created_at`
- UI: admin — create venue

### `GET /venues/all` 🔓
- Response: `List[VenueRead]`
- UI: venue picker when creating a concert

### `GET /venues/{id}` 🔓
- Response: `VenueRead`
- UI: venue detail (rarely its own page — usually inline on a concert page)

### `PUT /venues/update/{id}` 🔒 admin
- Request (`VenueUpdate`): same fields as create

### `DELETE /venues/delete/{id}` 🔒 admin
- Response: `{"msg": "Venue deleted successfully"}`

### `POST /concerts/add` 🔒 manager+
- Request (`ConcertCreate`): `venue_id` (uuid), `title` (str), `description` (str, optional),
  `capacity` (int, >0), `event_datetime` (datetime), `doors_open_at` (datetime, optional),
  `company_id` (uuid)
- Response (`ConcertRead`): adds `id`, `status`, `created_at`, `updated_at`
- UI: manager — create concert

### `GET /concerts/all` 🔓
- Response: `List[ConcertRead]`
- UI: concert listing / "upcoming shows" page

### `GET /concerts/{id}` 🔓
- Response: `ConcertRead`
- UI: concert detail page (pair with `/ticket_types/concert/{id}` and the performers endpoint
  below to build the full page)

### `GET /concerts/events-page` 🔓
- Response (`EventsPageRead`): `concerts` — each a `ConcertRead` plus its `venue`
- Errors: `404` if there are no concerts
- UI: public events page

### `GET /concerts/{id}/detail` 🔓 (auth optional)
One call for the whole concert page. The shared part is cached; the per-viewer fields are
computed per request and are `false`/empty for guests.
- Response (`ConcertDetailRead`): `concert`, `venue`, `ticket_types`, `lineup` (idols: `id`,
  `name`, `profile_image_url`, `color_hex`), `performing_groups` (`id`, `name`),
  `lottery_campaigns`, `direct_sale_campaigns`, and per viewer: `has_ticket`, `has_won_lottery`,
  `entered_campaign_ids`, `my_lottery_preferences`
- Errors: `404` if the concert doesn't exist
- Rate limit: 30/min per user, or per IP for guests
- UI: concert detail page — pick "apply to lottery" vs. "buy now" per tier from the campaign
  lists, and hide actions the fan can't take from the per-viewer fields

### `GET /concerts/manager-events-page` 🔓 (unauthenticated — see §0)
- Response (`ManagerEventsPageRead`): `concerts` (`List[ConcertRead]`), `venues`
  (`List[VenueRead]`, for the venue picker)
- UI: manager — concerts table and create form

### `PUT /concerts/update/{id}` 🔒 manager+ (company-scoped)
- Request (`ConcertUpdate`): same as create, plus `status` (str, optional)
- UI: manager — edit concert

### `DELETE /concerts/delete/{id}` 🔒 manager+ (company-scoped)
- Response: `{"msg": "Concert deleted successfully"}`

### `POST /concerts/performers/assign` 🔒 manager+
Attach an idol or group as a performer at a concert.
- Request (`ConcertPerformerAssign`): `concert_id` (uuid), `idol_id` (uuid, optional), `group_id`
  (uuid, optional) — exactly one of `idol_id`/`group_id` in practice
- Response (`ConcertPerformerRead`): adds `id`
- UI: manager — concert edit, "lineup" section

### `GET /concerts/performers/concert/{concert_id}` 🔓
- Response: `List[ConcertPerformerRead]`
- UI: concert detail page — lineup list

### `GET /concerts/performers/all` 🔓
Not used by the frontend.
- Response: `List[ConcertPerformerRead]`
- Errors: `404` if no concert has performers

### `DELETE /concerts/performers/{id}` 🔒 manager+
- Response: `{"msg": "Performer unassigned from concert successfully"}`
- UI: manager — remove a lineup entry

### `PUT /concerts/lottery-draw/{id}` 🔒 manager+ (company-scoped)
Run the lottery draw for every tier of one concert. The request only schedules it: the draw runs in
the Celery worker, and managers at the concert's company get `lottery_draw_triggered` now and
`lottery_draw_completed` or `lottery_draw_failed` when it finishes (§7). Fans get
`lottery_result` notifications; winners get a `pending_payment` ticket to pay for via
`POST /tickets/{ticket_id}/checkout`.
- Response: `200 {"msg": "Lottery draw task has been scheduled. ..."}` — returned even if the draw
  later fails (entries not closed yet, nothing left to draw); watch the notifications or
  `GET /lottery_entries/concert/{concert_id}/results` for the outcome
- Errors: `403` outside the manager's company, `404` unknown concert
- UI: manager — "Draw lottery" button on the concert edit page, disabled until entries close

### `POST /ticket_types/add` 🔒 manager+
A ticket tier for a concert (e.g. "VIP", "General") — `sale_method` decides whether it's sold via
lottery or (once built — see `project_status.md` §5) direct purchase.
- Request (`TicketTypeCreate`): `tier` (str), `price` (float, ≥0), `total_quantity` (int, ≥0),
  `sale_method` (str, default `"lottery"`), `concert_id` (uuid)
- Response (`TicketTypeRead`): adds `id`, `sold_quantity`, `created_at`
- UI: manager — concert edit, "ticket tiers" section

### `GET /ticket_types/concert/{concert_id}` 🔓
- Response: `List[TicketTypeRead]`
- UI: concert detail page — ticket tier list (price, remaining = `total_quantity - sold_quantity`)

### `GET /ticket_types/{id}` 🔓
- Response: `TicketTypeRead`
- UI: ticket tier detail / lottery-application confirmation step

### `PUT /ticket_types/update/{id}` 🔒 manager+
- Request (`TicketTypeUpdate`): `price` (optional), `total_quantity` (optional) — only these two
  are editable post-creation
- UI: manager — edit a ticket tier

### `DELETE /ticket_types/delete/{id}` 🔒 manager+
- Response: `{"msg": "Ticket type deleted successfully"}`

### `POST /lottery_campaigns/add` 🔒 manager+
- Request (`LotteryCampaignCreate`): `entry_start_at`, `entry_end_at` (both datetime),
  `payment_deadline_hours` (int, default 48), `ticket_type_id` (uuid). `max_entries_per_user` is
  not accepted (ignored if sent) — pinned to 1 server-side for now.
- Response (`LotteryCampaignRead`): adds `id`, `status`, `max_entries_per_user` (read-only, always
  1 for now), `draw_at` (null until actually drawn — written only by the draw job, never
  client-supplied), `created_at`
- UI: manager — set up a lottery for a ticket tier

### `GET /lottery_campaigns/ticket_type/{ticket_type_id}` 🔓
- Response: `List[LotteryCampaignRead]`
- UI: ticket tier page — "apply to this lottery" if a campaign is open

### `GET /lottery_campaigns/{id}` 🔓
- Response: `LotteryCampaignRead`
- UI: lottery application page

### `PUT /lottery_campaigns/update/{id}` 🔒 manager+
- Request (`LotteryCampaignUpdate`): same as create, plus `status` (optional)

### `DELETE /lottery_campaigns/delete/{id}` 🔒 manager+
- Response: `{"msg": "Lottery campaign deleted successfully"}`

### `POST /direct_sale_campaigns/add` 🔒 manager+ (company-scoped)
The on-sale window for a `sale_method="direct"` ticket type (`database-design.md` §3.21). A direct
tier can only be bought while one of its campaigns is `open` and now is inside the window.
- Request (`DirectSaleCampaignCreate`): `ticket_type_id` (uuid, must be a direct-sale tier),
  `sale_start_at`, `sale_end_at` (datetimes, end after start)
- Response (`DirectSaleCampaignRead`): adds `id`, `status` (`open` | `cancelled`), `created_at`
- Errors: `400` for a lottery ticket type, `403` outside the manager's company, `404` unknown
  ticket type, `422` if the window is inverted
- UI: manager — "put this tier on sale" on the concert edit page

### `GET /direct_sale_campaigns/ticket_type/{ticket_type_id}` 🔓
Not used by the frontend (the concert detail page already includes the campaigns).
- Response: `List[DirectSaleCampaignRead]`
- Errors: `404` if the ticket type has no campaigns

### `GET /direct_sale_campaigns/{id}` 🔓
Not used by the frontend.
- Response: `DirectSaleCampaignRead`

### `PUT /direct_sale_campaigns/update/{id}` 🔒 manager+ (company-scoped)
Not used by the frontend.
- Request (`DirectSaleCampaignUpdate`): `sale_start_at`, `sale_end_at` (both required), `status`
  (optional — `cancelled` stops sales early)
- Response: `DirectSaleCampaignRead`

### `DELETE /direct_sale_campaigns/delete/{id}` 🔒 manager+ (company-scoped)
Not used by the frontend.
- Response: `{"msg": "Direct sale campaign deleted successfully"}`

### `POST /lottery_entries/apply` 🔒 fan
Enter a lottery campaign. Enforced by both a service-layer check and a DB trigger (cap, and — see
`project_status.md` §4 item 9 — a required-preference check); trigger violations surface as a
normal HTTP error, not a 500.
- Request (`LotteryEntryApply`): `campaign_id` (uuid)
- Response (`LotteryEntryRead`): `id`, `campaign_id`, `user_id`, `status`, `created_at`, `drawn_at`
- Errors: `400` also covers a fan who already holds a live ticket for this concert (bought direct,
  or won an earlier tier) — `"You already hold a ticket for this concert"`, not just the
  cap/no-preference cases below
- UI: "Apply" button on the lottery application page — disable/hide once the fan has already
  entered, already holds a ticket for the concert, or once `entry_end_at` has passed

### `POST /lottery_entries/apply-batch` 🔒 fan
Apply to several of a concert's tiers in one request — all entries are created or none is, and it
uses one rate-limit slot (3/min).
- Request (`LotteryEntryApplyBatch`): `campaign_ids` (list of uuid, 1–10, no duplicates)
- Response: `List[LotteryEntryRead]`
- Errors: same as `/apply`, for whichever campaign fails first
- UI: concert page — "apply to every tier I ranked" button

### `GET /lottery_entries/mine` 🔒 fan
- Response: `List[LotteryEntryRead]`
- UI: "My lottery entries" page — show `status` (pending/won/lost) and `drawn_at`

### `GET /lottery_entries/campaign/{campaign_id}` 🔒 manager+
- Response: `List[LotteryEntryRead]`
- UI: manager — view entrants for a campaign (pre-draw or post-draw audit)

### `GET /lottery_entries/concert/{concert_id}/results` 🔒 manager+
Draw outcome for a whole concert at once (every ticket tier's campaign together, matching the
draw's own per-concert granularity — see `PUT /concerts/lottery-draw/{id}`), not raw entry rows
like `/campaign/{campaign_id}` above: only decided (`won`/`lost`) entries, each already folded
together with the winner's email and, for winners, their ticket's payment state — no second
request per winner needed.
- Response (`List[LotteryDrawResultRead]`): `lottery_entry_id`, `user_id`, `email`, `ticket_type_id`,
  `tier`, `status` (`won`|`lost` only), `drawn_at`, `ticket_id`, `payment_status`,
  `payment_deadline_at` — the last three are `null` for a `lost` row (no ticket was ever issued)
- Returns `[]` if the concert has no decided entries yet (including "hasn't been drawn at all")
- Errors: `404` (unknown concert), `403` (another company's concert)
- UI: manager — post-draw results table/export for a concert; poll or refresh after
  `lottery_draw_completed`/`lottery_draw_failed` notifications land (see `project_status.md` §8)

### `POST /lottery_preferences/set` 🔒 fan
Rank which ticket tiers (within one concert) the fan would accept, in priority order — required
before applying to some lotteries (see the trigger note above).
- Request (`LotteryPreferenceSet`): `concert_id` (uuid), `ticket_type_ids_in_order` (list[uuid],
  min 1 — order is the ranking)
- Response: `List[LotteryPreferenceRead]` (`id`, `concert_id`, `user_id`, `ticket_type_id`,
  `rank`, `created_at`)
- UI: pre-lottery "rank your preferred tiers" step, drag-to-reorder list of the concert's ticket
  types

### `GET /lottery_preferences/mine/{concert_id}` 🔒 fan
- Response: `List[LotteryPreferenceRead]`
- UI: same page, to show/edit an existing ranking

### `DELETE /lottery_preferences/mine/{concert_id}` 🔒 fan
Clears the fan's ranking for that concert.
- Response: `{"msg": "Preferences cleared successfully"}`
- UI: "clear my ranking" control

### `POST /tickets/checkout` 🔒 fan
Buy a `sale_method="direct"` ticket tier directly — no lottery, no draw. Only while the tier has
an `open` direct-sale campaign whose window contains now (see `Direct Sale Campaigns` above).
- Request (`TicketCheckoutCreate`): `ticket_type_id` (uuid, must be `sale_method="direct"`),
  `amount`, `gateway`, `simulate_succ`, `idempotency_key` — same shape as `POST /order/checkout`'s
  payment fields. `amount` must equal the tier price with tax. With `gateway="paypal"` the ticket
  and payment are created `pending`; read `pg_approval_url` from
  `GET /payment/status/ticket/{ticket_id}` — see §6's PayPal flow.
- Response (`TicketRead`)
- Errors: `400` covers, among other things, a fan with an unresolved lottery application for this
  concert — any of their `lottery_entries` still `pending` or `won` for a *different* tier under
  the same concert blocks a direct purchase (`"You have a pending or won lottery application for
  this concert — resolve it before buying a direct-sale ticket"`); only a `lost` entry (or none at
  all) clears this. Also `400` for "already holds a live ticket for this concert"
  (`trg_tickets_one_per_concert`), not on sale, sold out, or amount mismatch.
- UI: direct-purchase ticket page — surface the lottery-conflict error distinctly, since "you're
  still in the running for this concert's lottery" is a different message than "sold out"

### `POST /tickets/{ticket_id}/checkout` 🔒 fan
Pay for a ticket won in the lottery (status `pending_payment`, created by the draw).
- Request (`WonTicketCheckoutCreate`): `amount` (int, tier price with tax), `gateway`
  (`mock` | `paypal`), `simulate_succ` (mock only), `idempotency_key`
- Response: `TicketRead`
- Errors: `404` if the ticket isn't the caller's; `400` if it isn't a payable lottery win, the
  amount doesn't match, the gateway is unsupported, or `payment_deadline_at` has passed (the
  ticket is then marked `expired` and its seat released); `409` for a reused idempotency key
- UI: "My tickets" / lottery result page — "Pay now" before the deadline

### `POST /tickets/add` 🔒 admin
Manual issuance — a support/testing tool. Normal tickets come from the lottery draw
(`PUT /concerts/lottery-draw/{id}`) or direct-sale checkout (`POST /tickets/checkout`). The
recipient must be a fan with no live ticket for that concert.
- Request (`TicketCreate`): `ticket_type_id` (uuid), `user_id` (uuid), `lottery_entry_id` (uuid,
  optional — link back to the winning entry)
- Response (`TicketRead`): adds `id`, `payment_id`, `status`, `issued_code`, `reserved_at`,
  `payment_deadline_at`, `created_at`, `updated_at`
- UI: admin — manual ticket issuance tool

### `GET /tickets/mine` 🔒 fan
- Response: `List[TicketRead]`
- UI: "My tickets" page

### `GET /tickets/{id}` 🔒 fan
- Response: `TicketRead`
- UI: ticket detail (e.g. to show `issued_code` as a QR/barcode payload)

### `GET /tickets/concert/{concert_id}/sales` 🔒 manager+ (company-scoped)
Not used by the frontend.
- Request: query params `page` (default 1), `limit` (default 10, max 50)
- Response (`TicketSalesPageRead`): paged `data` of `ticket_id`, `tier`, `status`, `price`,
  `source` (`lottery` | `direct`), `created_at`
- Errors: `403` outside the manager's company, `404` unknown concert

### `PUT /tickets/update/{id}` 🔒 admin
- Request (`TicketUpdate`): `status`, `issued_code`, `payment_id`, `payment_deadline_at` (all
  optional)
- UI: admin — edit a ticket record

### `DELETE /tickets/delete/{id}` 🔒 admin
- Response: `{"msg": "Ticket deleted successfully"}`

---

## 5. Marketplace — Products, Categories, Album/Merch Details, Genres

### `POST /categories/add` 🔒 admin
- Request (`CategoryBase`): `name` (str, 1–100 chars)
- Response: `{"msg": "Category added successfully"}` — **not** the created category; refetch
  `/categories/all` to get its `id`
- UI: admin — category catalog

### `GET /categories/all` 🔓
- Response: `List[CategoryRead]` (`id`, `name`, `is_resale_capped`)
- UI: category filter/nav on the merch catalog page; category picker on the product form

### `PUT /categories/update` 🔒 admin
Note: `id` is a query param here, not a path segment.
- Request: query param `id` (uuid) + body (`CategoryUpdate`): `name`, `is_resale_capped`
  (optional)
- Response: `{"msg": "Category updated successfully"}`

### `DELETE /categories/delete/{id}` 🔒 admin
- Response: `{"msg": "Category deleted successfully"}`

### `GET /products/all` 🔓
- Response: `List[ProductRead]` (`id`, `name`, `price`, `description`, `quantity`, `image_url`,
  `category` — the category *name* as a string, not the id)
- UI: merch catalog grid

### `GET /products/store-page` 🔓
- Response (`StorePageRead`): `products` (`List[ProductCard]`), `groups` (`id`, `name` — for the
  artist filter). A `ProductCard` is `id`, `name`, `price`, `description`, `quantity`,
  `image_url`, `category` (name), `album` (album details or `null`), `genres`, `artist` (the
  credited idol/group or `null`), `resale_cap_quantity` (per-fan lifetime cap, or `null` if the
  category isn't capped)
- Errors: `404` if there are no products
- UI: store page

### `GET /products/{id}/detail` 🔓
- Response (`ProductDetailRead`): `product` (`ProductCard`), `recommendations`
  (`List[ProductCard]`)
- Errors: `404` if the product doesn't exist
- UI: product detail page

### `GET /products/manager-products-page` 🔓 (unauthenticated — see §0)
- Request: query param `company_id` (uuid, optional — filters to that company's products)
- Response (`ManagerProductsPageRead`): `products` (`List[ProductRead]`)
- UI: manager — products table

### `GET /products/manager-product-form-page` 🔓 (unauthenticated — see §0)
- Request: query param `company_id` (uuid, optional)
- Response (`ManagerProductFormPageRead`): `products`, `categories`, `idols`, `groups`, `colors`
  — everything the create/edit form's pickers need
- UI: manager — create/edit product form

### `GET /products/{id}/sales` 🔒 manager+ (company-scoped)
- Request: query params `page` (default 1), `limit` (default 10, max 50)
- Response (`ProductSalesPageRead`): paged `data` of `order_id`, `order_status`,
  `order_created_at`, `quantity`, `price`, `line_total`
- Errors: `403` outside the manager's company, `404` unknown product
- UI: manager — per-product sales table

### `GET /products/search/{id}` 🔓
Not used by the frontend (use `GET /products/{id}/detail`).
- Response (`ProductWithCategoryRead`): `id`, `name`, `price`, `description`, `quantity`,
  `image_url`, `category` (the full `CategoryRead` object)

### `GET /products/pagination` 🔓
- Request: query params `page` (int, default 1), `limit` (int, default 10, max 50)
- Response: `{"page", "limit", "count", "data": [Product...]}` — the only endpoint with real
  pagination; prefer this over `/all` for the main catalog page
- UI: merch catalog grid, paged

### `GET /products/filter` 🔓
- Request: query params `category` (str, required), `name` (str, optional), `min_price` (int,
  optional), `max_price` (int, optional), `limit`/`page` (as above)
- Response: same shape as `/pagination`
- UI: merch catalog with filters/search applied

### `POST /products/add_product` 🔒 manager+ — **multipart/form-data**, not JSON
- Request (form fields): `name` (str), `price` (float), `description` (str), `quantity` (int),
  `category_id` (uuid), `image` (file, optional, same constraints as idol images)
- Response: `{"msg": "Product added successfully"}` — refetch to get the new product's `id`
- UI: manager — create product. Deliberately unscoped to any company at creation (see
  `project_status.md` §4 item 10) — a bare product has no idol/group tie until an album/merch
  detail is attached to it (below)

### `POST /products/add_with_detail` 🔒 manager+ (company-scoped) — **multipart/form-data**
Creates a product and its album or merch detail row in one transaction, so a product is never left
without an owner. This is what the manager product form uses.
- Request (form fields): the `add_product` fields (`name`, `price`, `description`, `quantity`,
  `category_id`, `image`) plus `detail_kind` (`album` | `merch`), `idol_id`/`group_id` (album: at
  least one; merch: exactly one), album-only `release_date`, `track_count`, `format` (default
  `physical`), merch-only `edition`, `color_id`
- Response: `{"msg": "Product added successfully"}`
- Errors: `422` for a bad field combination, `400` for a rejected image, `403` for an idol/group
  outside the manager's company

### `PUT /products/update/{id}` 🔒 manager+ — **company-scoped once the product has album/merch
details attached**
- Request (`ProductCreate`): `name`, `price`, `description`, `quantity`, `image_url`,
  `category_id`
- Response: `{"msg": "Product Updated successfully"}` — `400` if `category_id` doesn't reference
  an existing category (`project_status.md` item 13)
- UI: manager — edit product. `403` if the product is tied (via album/merch details) to a
  different company than the manager's

### `POST /products/{id}/image` 🔒 manager+ (same company-scoping as update)
Replace a product's image only.
- Request: `multipart/form-data`, `image` (file, required)
- Response: `{"msg": "Product image updated successfully"}`
- UI: manager — edit product, "change photo"

### `DELETE /products/delete/{id}` 🔒 manager+ (same company-scoping as update)
- Response: `{"detail": "Product Deleted successfully"}` — note the key is `detail`, not `msg`,
  unlike every other delete endpoint on this list

### `POST /products/bulk_products` 🔒 manager+
- Request: `List[ProductCreate]` (JSON array; each item needs `category_id` — no image support
  in bulk)
- Response: `{"msg": "<n> bulk products added successfully"}`
- UI: manager — CSV/bulk import tool, if built

### `POST /album_details/add` 🔒 manager+
Attaches album-specific data to an existing product, and is what establishes that product's
company ownership.
- Request (`AlbumDetailCreate`): `product_id` (uuid, must already exist), `idol_id` (uuid,
  optional), `group_id` (uuid, optional — exactly one of the two required), `release_date` (date,
  optional), `track_count` (int, optional, >0), `format` (str, default `"physical"`) — no cover
  image field here; every product's image, album or not, is `products.image_url` only
  (`POST /products/{id}/image`), see `database-design.md` §3.16
- Response (`AlbumDetailRead`): `product_id`, `idol_id`, `group_id`, plus base fields
- `400` if the referenced `idol_id`/`group_id` is deactivated (`is_active=false`) — new releases
  can't be attached to an inactive artist (database-design.md §3.3/§3.4)
- UI: manager — "this is an album" toggle on the product form, revealing these fields

### `GET /album_details/all` 🔓
- Response: `List[AlbumDetailRead]`
- UI: merch catalog — album-specific badges/filters

### `GET /album_details/{product_id}` 🔓
- Response: `AlbumDetailRead`
- UI: product detail page (album variant)

### `PUT /album_details/update/{product_id}` 🔒 manager+ (company-scoped)
- Request (`AlbumDetailUpdate`): `release_date`, `track_count`, `format`
  (`idol_id`/`group_id` immutable after creation)

### `DELETE /album_details/delete/{product_id}` 🔒 manager+ (company-scoped)
- Response: `{"msg": "Album details deleted successfully"}`

### `POST /genres/add` 🔒 manager+
- Request (`GenreCreate`): `name` (str, 1–100 chars)
- Response (`GenreRead`): adds `id`
- UI: manager — genre catalog (shared, not per-company)

### `GET /genres/all` 🔓
- Response: `List[GenreRead]`
- UI: genre picker on an album's edit form

### `DELETE /genres/delete/{id}` 🔒 admin
- Response: `{"msg": "Genre deleted successfully"}`

### `POST /genres/album_genres/assign` 🔒 manager+
- Request (`AlbumGenreAssign`): `product_id` (uuid), `genre_id` (uuid)
- Response (`AlbumGenreRead`): `product_id`, `genre_id`
- UI: album edit page — "genres" multi-select

### `GET /genres/album_genres/album/{product_id}` 🔓
- Response: `List[AlbumGenreRead]`
- UI: album detail page — genre tags

### `GET /genres/album_genres/all` 🔓
Not used by the frontend.
- Response: `List[AlbumGenreRead]` (`product_id`, `genre_id`)
- Errors: `404` if no album has a genre

### `DELETE /genres/album_genres/{product_id}/{genre_id}` 🔒 manager+
- Response: `{"msg": "Genre unassigned from album successfully"}`
- UI: album edit page — remove a genre tag

### `POST /merch_details/add` 🔒 manager+
Same pattern as album details, for official merch tied to one idol or one group — a lightstick, a
tour hoodie, anything sold under one clear banner. (Originally `/lightstick_details/*`, scoped to
lightsticks only; generalized when the `Lightstick` category was merged into `Merch` — see
`database-design.md` §3.15/§3.17. Request/response field shape is unchanged from before the
rename.)
- Request (`MerchDetailCreate`): `product_id` (uuid), `idol_id` (uuid, optional), `group_id`
  (uuid, optional — exactly one), `edition` (str, optional), `color_id` (uuid, optional — links to
  `idol_colors`)
- Response (`MerchDetailRead`): adds `created_at`
- `400` if the referenced `idol_id`/`group_id` is deactivated (`is_active=false`) — same rule as
  `POST /album_details/add`
- UI: manager — attach ownership on the product form (a lightstick-specific toggle no longer makes
  sense once this covers any branded merch, not just lightsticks)

### `GET /merch_details/all` 🔓
- Response: `List[MerchDetailRead]`

### `GET /merch_details/{product_id}` 🔓
- Response: `MerchDetailRead`
- UI: product detail page (merch variant)

### `PUT /merch_details/update/{product_id}` 🔒 manager+ (company-scoped)
- Request (`MerchDetailUpdate`): `edition`, `color_id`

### `DELETE /merch_details/delete/{product_id}` 🔒 manager+ (company-scoped)
- Response: `{"msg": "Merch details deleted successfully"}`

---

## 6. Shopping — Cart, Shipping, Order, Payment

### `POST /cart/add_cart` 🔒 fan
- Request (`CartItem`): `product_id` (uuid), `quantity` (int, ≥1)
- Response: not schema-enforced; the raw `Cart` row (`id`, `product_id`, `quantity`, `user_id`,
  `price`, `total_price`) — adding an item already in the cart increments its quantity rather
  than creating a duplicate row
- UI: "Add to cart" button anywhere a product is shown

### `GET /cart/see_cart` 🔒 fan
- Response: not schema-enforced; `{"items": [Cart...], "total_price": float}`
- UI: cart page / cart drawer

### `DELETE /cart/delete_cart/{cart_id}` 🔒 fan
`cart_id` is the cart row's id (from `see_cart`'s `items`), not the product id.
- Response: `{"msg": "Cart item deleted successfully"}`
- UI: cart page — remove item

### `POST /shipping_addresses/add` 🔒 fan
- Request (`ShippingBase`): `address_line1` (str), `address_line2` (str, optional), `city` (str),
  `postal_code` (int — **note:** integer-typed, so alphanumeric postal codes like UK/Canada
  formats can't round-trip; see `project_status.md` §4 item 5), `state` (str), `country` (str)
- Response (`ShippingAddress`): adds `id`, `user_id`
- UI: checkout — "add a new address," and account settings

### `GET /shipping_addresses/fetch` 🔒 fan
- Response: `List[ShippingAddress]`
- UI: checkout — saved-address picker; account settings — address list

### `GET /shipping_addresses/fetch_byid/{address_id}` 🔓 — **currently broken**
- Response: `ShippingAddress`
- Currently returns `500` on every request: the route has no auth dependency but its rate limiter
  keys on the logged-in user. It also doesn't check that the address belongs to the caller
  (`docs/bugs.md` #28). Use `GET /shipping_addresses/fetch` instead until it's fixed.
- UI: address detail/edit form prefill

### `PUT /shipping_addresses/update/{address_id}` 🔒 fan
- Request (`ShippingBase`): same fields as add
- Response: `{"msg": "Address updated successfully"}`

### `DELETE /shipping_addresses/delete/{address_id}` 🔒 fan
- Response: `{"msg": "Address deleted successfully"}`

### `POST /order/checkout` 🔒 fan
Converts the cart into an order and a payment in one call. **Response is the `Order`, not the
payment** — it has no `payment_id`/`pg_order_id` of its own, so a `gateway="paypal"` checkout must
follow up with `GET /payment/status/order/{order_id}` (below) to fetch the payment and its
`pg_approval_url`. See "PayPal checkout flow" below for the full redirect sequence.
- Request (`PaymentCreate`): `amount` (int — must equal the cart's current total, checked
  server-side), `shipping_address_id` (uuid), `gateway` (`"mock"` | `"paypal"`, default `"mock"`),
  `simulate_succ` (bool, optional — mock gateway only, forces a mock success/failure),
  `idempotency_key` (uuid, **required** — generate a fresh one per checkout attempt; retrying the
  same key against an already-resolved payment returns `409`, not a duplicate order)
- Response (`Order`): `id`, `user_id`, `shipping_address_id`, `total_price`, `status`
  (`"pending"|"confirmed"|"cancelled"` — a `paypal` checkout comes back `"pending"`, not
  `"confirmed"`, until the payment is captured), `created_at`, `items`, `shippingstatus`
  (always present — every order gets a `shipping_status` row at `"pending"` in the same checkout
  transaction, not created lazily later), `shippingaddress`
- Errors: `404` (`cart_empty` / `address_not_found`), `400` (`insufficient_stock`,
  `amount_mismatch`, `unsupported_gateway`, `resale_cap_exceeded`), `403` (`fan_only_purchase`),
  `409` (`duplicate_idempotency_key`). A declined mock payment is **not** an error: `200` with
  `status: "cancelled"` — distinguish these in the UI rather than showing one generic "checkout failed"
- UI: checkout page's final "place order" action

### `GET /order/fetch_placed_order` 🔒 fan
- Response: `List[Order]` — each `Order` includes `status` (`"pending"|"confirmed"|"cancelled"`),
  nested `items` (`OrderItem[]`), `shippingstatus`, `shippingaddress`
- UI: "My orders" list

### `GET /order/single_placed_order/{order_id}` 🔒 fan
- Response: `Order`
- UI: order detail page

### `PATCH /order/cancel/{order_id}` 🔒 fan
- Response: `Order` (updated) — `400` if the order has already shipped
- UI: order detail page — "cancel order" button

### `GET /order/shipping_status/{order_id}` 🔒 fan
- Response: not schema-enforced (raw `shipping_status` row); `ShippingStatusResponse`-shaped —
  `status`, `updated_at` (when `status` last changed)
- UI: order detail page — shipping tracker

### `PATCH /order/update_shipping_status/{order_id}` 🔒 admin
Free-form override — sets any status, including going backwards. A manual-correction tool, not the
everyday fulfillment path; see `PATCH /order/{order_id}/ship` below for that.
- Request (`ShippingStatus` enum): `"pending" | "processing" | "shipped" | "delivered" |
  "cancelled"`
- Response: not schema-enforced (raw `shipping_status` row, same shape as the `GET` above, despite
  the type hint saying `Order` — the service returns the `shipping_status` row, not the order)
- `400` if the order is already `cancelled`
- UI: admin — fulfillment/shipping dashboard, manual override

### `PATCH /order/{order_id}/ship` 🔒 manager+ (company-scoped)
The everyday "mark shipped" action — one button, no status picker. Only moves `pending`/`processing`
→ `shipped`; a manager may only ship an order containing at least one of their own company's
products (an admin isn't scoped). Writes an `order_shipped` in-app notification to the buyer in the
same commit as the status flip.
- Response (`Order`): the full updated order, same shape as `POST /order/checkout`'s response —
  `shippingstatus.status` is now `"shipped"` with a fresh `updated_at`
- Errors: `404` (order doesn't exist), `403` (manager's company has no product in this order), `400`
  (order isn't in `pending`/`processing` — already shipped/delivered, or cancelled)
- UI: manager orders page — a "Ship" button per order row, or on the order detail page

### `GET /order/manager-orders-page` 🔒 manager+ (company-scoped)
- Request: query params `page` (default 1), `limit` (default 10, max 50), `company_id` (uuid,
  admins only — a manager always gets their own company)
- Response (`ManagerOrdersPageRead`): paged `data` of `id`, `buyer_name`, `buyer_email`, `status`,
  `created_at`, `items` (only this company's lines, plus ownerless products), `company_total`,
  `shippingstatus`
- UI: manager — orders to ship

### `GET /payment/status/order/{order_id}` 🔒 fan
Read-only lookup of the order's payment. `404` if there's no payment for that order, or the order
isn't the caller's.
- Response (`PaymentResponse`): `id`, `order_id`, `ticket_id` (null here — set only for a ticket
  payment), `user_id`, `amount`, `status` (`"pending"|"success"|"failed"|"cancelled"`),
  `payment_gateway` (`"mock"|"paypal"`), `is_paid`, `pg_order_id`, `pg_payment_id`, `pg_signature`,
  `pg_approval_url` (PayPal's redirect link — see below; always `null` for `"mock"` or once a
  payment has resolved), `created_at`, `updated_at`
- UI: order detail / checkout success page — poll this while waiting on an async gateway

### `GET /payment/status/ticket/{ticket_id}` 🔒 fan
Same `PaymentResponse` shape as above, looked up by `ticket_id` instead (`order_id` null,
`ticket_id` set). Used the same way for a direct-sale ticket checkout.

### `GET /payment/status/all` 🔒 fan
- Response: `List[PaymentResponse]` — `[]` if the fan has no payments
- UI: "My payments" page, if surfaced separately from orders

### PayPal checkout flow (redirect + capture)
Everything below only applies when `gateway="paypal"` was passed to `POST /order/checkout`,
`POST /tickets/checkout` or `POST /tickets/{ticket_id}/checkout`. The mock gateway resolves synchronously in that one call; PayPal doesn't
— the fan has to leave the app to approve the payment on PayPal's site first.

1. **Checkout** — `POST /order/checkout` (or `/tickets/checkout`) with `gateway="paypal"`. The
   order/ticket comes back `"pending"` — no error, this is expected, not a stuck state.
2. **Fetch the approval link** — `GET /payment/status/order/{order_id}` (or
   `.../ticket/{ticket_id}`) and read `pg_approval_url` off the response.
3. **Redirect the fan** to `pg_approval_url` (a `paypal.com` page, not this API). This is a full
   page redirect, not an API call — treat it like sending the fan to a third-party checkout, same
   as any other redirect-based payment flow.
4. **Fan approves and PayPal redirects back** to the frontend route
   `{FRONTEND_BASE_URL}/payment/paypal/return` (set in
   `app/utils/paypal_client.py::create_order`). PayPal appends `token` (the PayPal order id — the
   same value as `pg_order_id`) and `PayerID` as query params.
5. **Capture** — the frontend route from step 4 calls `POST /payment/paypal/capture/{pg_order_id}`
   (using the `token` query param as `pg_order_id`) 🔒 fan. Response is the updated
   `PaymentResponse` — `status` is now `"success"` or `"failed"`.
   - `404` here means: not found, already resolved (e.g. the webhook below beat this call to it —
     treat that as a normal race, not an error to surface), or the payment doesn't belong to the
     caller.
6. **Cancellation**: if the fan backs out on PayPal's side instead, PayPal redirects to
   `{FRONTEND_BASE_URL}/payment/paypal/cancel` with `token` — no capture call needed, the order/ticket simply stays `"pending"` (it isn't
   auto-cancelled; nothing currently sweeps up abandoned PayPal checkouts, see
   `project_status.md`).

### `POST /payment/paypal/webhook` 🔓 (PayPal signature-verified)
**The frontend never calls this directly** — the endpoint exists purely for
PayPal's own server-to-server delivery, as a reconciliation backstop for the same
`finalize_paypal_payment` capture logic in case step 5 never happens (fan closes the tab after
approving, etc.). It's mentioned here only so it isn't mistaken for something the frontend needs to
implement.

## 7. Notifications

No WebSocket/SSE layer exists — this is a short-polling design (database-design.md §3.19). A
client with no push mechanism should poll `GET /notifications/unread-count` on an interval (15-30s
suggested; pause while the tab/app is backgrounded) and only fetch the heavier `GET
/notifications/mine` when the count goes up, rather than re-fetching full notification bodies on
every tick.

### `GET /notifications/unread-count` 🔒 fan
Cheap, meant to be polled — see above. Rate-limited at 30 req/60s per user, well above any sane
poll interval; a `429` here means the client is polling too aggressively, not a real error to
surface to the user.
- Response (`NotificationUnreadCount`): `{"count": int}`
- UI: nav bar notification bell badge

### `GET /notifications/mine` 🔒 fan
- Query: `unread_only` (bool, default `false`)
- Response: `List[NotificationRead]` — `id`, `user_id`, `type`
  (`"order_confirmation"|"order_shipped"|"ticket_confirmation"|"lottery_registered"|
  "lottery_draw_triggered"|"lottery_draw_failed"|"lottery_draw_completed"|"lottery_result"|
  "lottery_payment_reminder"|"lottery_payment_confirmation"|"event_reminder"|"password_reset"`),
  `order_id`/`ticket_id`/`lottery_entry_id`/`concert_id` (exactly one set, depending on `type`),
  `status`, `sent_at`, `is_read`, `read_at`, `created_at`
- Returns `[]` when there are none (or none matching `unread_only`)
- UI: notification feed/dropdown

### `POST /notifications/{notification_id}/read` 🔒 fan
- Response: `NotificationRead` (updated)
- Errors: `404` (not found), `403` (belongs to another user)
- UI: marking one notification read on click/dismiss

### `POST /notifications/read-all` 🔒 fan
- Response: `{"msg": "<n> notification(s) marked as read"}`
- UI: "mark all as read" action

## 8. Inquiries (contact form, お問い合わせ)

### `POST /inquiries/submit` 🔓 (auth optional)
Anyone can submit. If a valid `Authorization` header is sent, the inquiry is linked to that
account; the `email` field is still required either way.
- Body (`InquiryCreate`): `email` (valid email), `topic`
  (`"tickets"|"lottery"|"orders"|"payment"|"account"|"other"`), `content` (string, 5–2000
  characters, counted as Unicode code points; leading/trailing whitespace, including the
  full-width space `U+3000`, is trimmed before the length check). The minimum is 5 because a
  complete Japanese question can be very short.
- `email` must use normal (half-width) characters. A full-width `＠` or letters get a `422`, so
  the frontend should normalize the email with NFKC before sending.
- Response (`InquiryCreated`): `{"id": uuid, "msg": "Your inquiry has been received"}`
- Side effect: a confirmation email to `email` with the topic and reference id (never the
  message text). An address that already received 3 confirmations in the past hour gets no
  further email, but the response is still `200` and the inquiry is still saved, so don't
  promise the user an email in the UI copy.
- Errors: `422` (validation: bad email, unknown topic, content too short/long), `429` (more than
  3 submissions per 10 minutes from the same account, or the same IP for guests; `detail` says
  how many seconds to wait)
- UI: contact page form

### `POST /inquiries/instant-answer` 🔓 (auth optional)
An AI answer taken only from the site FAQ, meant to be shown before the user submits the contact
form. Nothing is saved. Logged-in users are rate-limited per account, guests per IP.
- Body (`InstantAnswerRequest`): `topic` (same values as `/inquiries/submit`), `content` (5–2000
  characters, same rules as `/inquiries/submit`), `lang` (`"en"` or `"ja"`, default `"en"`).
- `lang` picks which FAQ is used: `app/content/faq.md` (`en`) or `app/content/faq.ja.md` (`ja`).
  Send the UI's current language. The answer comes back in the language of the question, so a
  Japanese question gets a Japanese answer even with `lang: "en"`, but matching `lang` gives
  wording closest to the site's own.
- Response (`InstantAnswerRead`): `{"answerable": bool, "answer": string | null}`. `answer` is
  set only when `answerable` is `true`.
- `answerable: false` covers every case where there's nothing to show: the FAQ doesn't cover the
  question, the feature is switched off (no `ANTHROPIC_API_KEY`), or the AI call failed. It is
  never an error; just show the form.
- Errors: `422` (validation), `429` (more than 5 requests per 10 minutes). Treat a `429` like
  `answerable: false` rather than showing an error.
- Can take several seconds. Show a loading state and let the user skip straight to submitting.
- UI: contact page, between typing the question and the submit button. Label the answer as
  AI-generated.
