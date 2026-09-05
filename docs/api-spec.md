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
enforcing it, so treat those as "best current description," not a contract, until `project_status.md`
§3's live-server verification gap is closed.

## 0. Conventions

**Base URL.** No global prefix — every path below is mounted at the app root (`main.py` does
`app.include_router(...)` with no `prefix=`). Interactive docs are served at `/docs` (Swagger UI,
auto-generated from the same route definitions) and `/redoc` — useful for exploring exact schemas
live once a server is running, this file is for planning UI against before/without one.

**Auth.** JWT bearer tokens. Obtain one via `POST /account/login` (see §1) and send it as
`Authorization: Bearer <access_token>` on every endpoint marked 🔒 below. There is no cookie-based
session — the frontend owns storing and attaching the token. A request to a 🔒 endpoint with a
missing/invalid/expired token gets `401`; a valid token but wrong role gets `403` (see role
legend). `require_manager_or_admin` only checks *role*, not company ownership — several services
additionally 403 when a manager acts outside their own company's resources (noted per-endpoint as
"company-scoped").

**Role legend** (from `app/deps/auth.py`, checked against `Users.role`):
- 🔓 — no auth required (public)
- 🔒 fan — any authenticated user (`get_current_user`); no role restriction beyond being logged in
- 🔒 manager+ — `require_manager_or_admin`: role is `manager` or `admin`
- 🔒 admin — `require_admin`: role is `admin` only

**Error shape.** Most errors are FastAPI's default `HTTPException` body: `{"detail": "<message>"}`.
A handful of endpoints return `{"msg": "<message>"}` on success for simple actions (deletes,
password changes) instead of the resource itself — called out per-endpoint below since it affects
whether the frontend can optimistically update from the response or must refetch.

**Pagination.** Only `GET /products/pagination` implements real page/limit pagination today
(`{"page", "limit", "count", "data"}`). Every other `/all` list endpoint returns the full
collection unpaginated — fine for this dataset's size, but don't build infinite-scroll against
them expecting a `next` cursor that doesn't exist.

**Image uploads.** `POST /idols/add` and `POST /products/add_product` are `multipart/form-data`,
not JSON — every other write endpoint on this list is JSON. See §3 (`Idols`) and §5 (`Products`)
for the exact form fields. Uploaded images are served back from whatever `LOCAL_UPLOAD_URL_PREFIX`
resolves to (default `/uploads/...`) or a real S3/CDN URL, depending on backend deploy config —
either way, `image_url`/`profile_image_url` in the response is a ready-to-use `<img src>`.

**Rate limits.** A handful of endpoints (mostly public list/search endpoints and anything
touching auth or payment) are rate-limited per-IP or per-user; a `429` means back off, not a bug.
Not exhaustively listed below — see `app/cache/rate_limit.py` if a specific limit matters to a
retry/backoff strategy.

## 1. Suggested frontend page structure

A starting page inventory, grouped by who uses it, with the endpoint sections each pulls from.
Not prescriptive — just a shape that maps cleanly onto what the backend actually supports today,
so a UI can be scaffolded before every endpoint is wired in.

**Public (no login):**
- Home / landing — highlights across idols, groups, upcoming concerts (§3, §4)
- Idol profile page — §3 `Idols`, plus their positions (§3 `Positions`) and merch (§5)
- Group profile page — §3 `Groups`, plus member roster (§3 `Positions`)
- Concert detail page — §4 `Concerts`, its ticket types (§4 `Ticket Types`), performers
- Merch catalog + product detail — §5 `Products`, `Categories`, `Album Details`, `Lightstick
  Details`, `Genres`
- Login / register / email verify / forgot-password / reset-password — §2

**Fan (logged in, any role):**
- My profile — §2 `Profile`
- Cart — §6 `Cart`
- Checkout — §6 `Order` (`/checkout`), `Shipping Addresses`, `Payment`
- My orders (list + detail + cancel + shipping status) — §6 `Order`
- My payment status — §6 `Payment`
- My tickets — §4 `Tickets` (`/mine`)
- Lottery: apply to a campaign, rank ticket-type preferences, see my entries — §4 `Lottery
  Campaigns`, `Lottery Preferences`, `Lottery Entries`

**Manager (their own company's idols/groups/concerts/products):**
- Manager dashboard — entry point into the sections below, scoped to their `company_id`
- Manage idols / groups / positions / idol colors — §3 (create/edit; delete on colors is
  admin-only)
- Manage concerts, ticket types, performer assignments — §4 (campaigns/entries listing is
  manager+; drawing/issuing tickets is not exposed here — see `project_status.md` §5)
- Manage products, album details, lightstick details, genre assignments — §5 (product image
  upload/replace, update, delete are company-scoped — see the 403 note under `Products`)

**Admin (site-wide):**
- Manage management companies — §2 `Management Companies`
- Manage categories, genres (delete), venues — §5, §4
- Promote a user to admin — §2 `Profile` (`/make-admin`)
- Manually issue / edit / delete tickets — §4 `Tickets` (the only way tickets get created today —
  no automated draw job yet, see `project_status.md` §5)
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
- Response (`GroupRead`): adds `id`, `created_at`, `updated_at`
- UI: manager — create group

### `GET /groups/all` 🔓
- Response: `List[GroupRead]`
- UI: group directory / home page carousel

### `GET /groups/{id}` 🔓
- Response: `GroupRead`
- UI: group profile page

### `PUT /groups/update/{id}` 🔒 manager+ (company-scoped)
- Request (`GroupUpdate`): `name`, `debut_date`, `description`
- UI: manager — edit group

### `DELETE /groups/delete/{id}` 🔒 manager+ (company-scoped)
- Response: `{"msg": "Group deleted successfully"}`

### `POST /idols/add` 🔒 manager+ — **multipart/form-data**, not JSON
- Request (form fields): `name` (str, required), `company_id` (uuid, required), `group_id` (uuid,
  optional), `date_of_birth` (date, optional), `hometown` (str, optional), `color_id` (uuid,
  optional), `short_intro` (str, optional, ≤500 chars), `long_description` (str, optional),
  `image` (file, optional — max 5MB, `image/jpeg|png|webp|gif`)
- Response (`IdolRead`): all the above plus `id`, `profile_image_url`, `created_at`, `updated_at`
- UI: manager — create idol (with photo upload in the same form)

### `GET /idols/all` 🔓
- Response: `List[IdolRead]`
- UI: idol directory / home page

### `GET /idols/{id}` 🔓
- Response: `IdolRead`
- UI: idol profile page

### `PUT /idols/update/{id}` 🔒 manager+ (company-scoped) — **JSON**, not multipart
Updates every field except the image — use the dedicated image endpoint below for that.
- Request (`IdolUpdate`): same fields as `IdolCreate` minus `company_id` (ownership is immutable)
- UI: manager — edit idol (text fields)

### `DELETE /idols/delete/{id}` 🔒 manager+ (company-scoped)
- Response: `{"msg": "Idol deleted successfully"}`

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

### `DELETE /concerts/performers/{id}` 🔒 manager+
- Response: `{"msg": "Performer unassigned from concert successfully"}`
- UI: manager — remove a lineup entry

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
- Request (`LotteryCampaignCreate`): `entry_start_at`, `entry_end_at`, `draw_at` (all datetime),
  `payment_deadline_hours` (int, default 48), `max_entries_per_user` (int, default 1),
  `ticket_type_id` (uuid)
- Response (`LotteryCampaignRead`): adds `id`, `status`, `created_at`
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

### `POST /lottery_entries/apply` 🔒 fan
Enter a lottery campaign. Enforced by both a service-layer check and a DB trigger (cap, and — see
`project_status.md` §4 item 9 — a required-preference check); trigger violations surface as a
normal HTTP error, not a 500.
- Request (`LotteryEntryApply`): `campaign_id` (uuid)
- Response (`LotteryEntryRead`): `id`, `campaign_id`, `user_id`, `status`, `created_at`, `drawn_at`
- UI: "Apply" button on the lottery application page — disable/hide once the fan has already
  entered, or once `entry_end_at` has passed

### `GET /lottery_entries/mine` 🔒 fan
- Response: `List[LotteryEntryRead]`
- UI: "My lottery entries" page — show `status` (pending/won/lost) and `drawn_at`

### `GET /lottery_entries/campaign/{campaign_id}` 🔒 manager+
- Response: `List[LotteryEntryRead]`
- UI: manager — view entrants for a campaign (pre-draw or post-draw audit)

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

### `POST /tickets/add` 🔒 admin
The only way a ticket gets created today — manual issuance, since the lottery draw job doesn't
exist yet (`project_status.md` §5).
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

### `PUT /tickets/update/{id}` 🔒 admin
- Request (`TicketUpdate`): `status`, `issued_code`, `payment_id`, `payment_deadline_at` (all
  optional)
- UI: admin — edit a ticket record

### `DELETE /tickets/delete/{id}` 🔒 admin
- Response: `{"msg": "Ticket deleted successfully"}`

---

## 5. Marketplace — Products, Categories, Album/Lightstick Details, Genres

### `POST /Categories/add` 🔒 admin
- Request (`CategoryBase`): `name` (str, 1–100 chars)
- Response: `{"msg": "Category added successfully"}` — **not** the created category; refetch
  `/Categories/all` to get its `id`
- UI: admin — category catalog

### `GET /Categories/all` 🔓
- Response: `List[CategoryRead]` (`id`, `name`, `is_resale_capped`)
- UI: category filter/nav on the merch catalog page; category picker on the product form

### `PUT /Categories/update` 🔒 admin
Note: `id` is a query param here, not a path segment.
- Request: query param `id` (uuid) + body (`CategoryUpdate`): `name`, `is_resale_capped`
  (optional)
- Response: `{"msg": "Category updated successfully"}`

### `DELETE /Categories/delete/{id}` 🔒 admin
- Response: `{"msg": "Category deleted successfully"}`

### `GET /products/all` 🔓
- Response: `List[ProductRead]` (`id`, `name`, `price`, `description`, `quantity`, `image_url`,
  `category` — the category *name* as a string, not the id)
- UI: merch catalog grid

### `GET /products/search/{id}` 🔓
- Response: not schema-enforced; the raw `Product` ORM row (id/name/price/description/quantity/
  category_id/image_url) — no `response_model`, so field set isn't guaranteed stable
- UI: product quick-view

### `GET /products/pagination`
- Request: query params `page` (int, default 1), `limit` (int, default 10, max 50)
- Response: `{"page", "limit", "count", "data": [Product...]}` — the only endpoint with real
  pagination; prefer this over `/all` for the main catalog page
- UI: merch catalog grid, paged

### `GET /products/filter`
- Request: query params `category` (str, required), `name` (str, optional), `min_price` (int,
  optional), `max_price` (int, optional), `limit`/`page` (as above)
- Response: same shape as `/pagination`
- UI: merch catalog with filters/search applied

### `POST /products/add_product` 🔒 manager+ — **multipart/form-data**, not JSON
- Request (form fields): `name` (str), `price` (float), `description` (str), `quantity` (int),
  `category_id` (uuid), `image` (file, optional, same constraints as idol images)
- Response: `{"msg": "Product added successfully"}` — refetch to get the new product's `id`
- UI: manager — create product. Deliberately unscoped to any company at creation (see
  `project_status.md` §4 item 10) — a bare product has no idol/group tie until an album/lightstick
  detail is attached to it (below)

### `PUT /products/update/{id}` 🔒 manager+ — **company-scoped once the product has album/lightstick
details attached**
- Request (`ProductCreate`): `name`, `price`, `description`, `quantity`, `image_url`,
  `category_id`
- Response: `{"msg": "Product Updated successfully"}`
- UI: manager — edit product. `403` if the product is tied (via album/lightstick details) to a
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
  optional), `track_count` (int, optional, >0), `format` (str, default `"physical"`),
  `cover_image_url` (str, optional)
- Response (`AlbumDetailRead`): `product_id`, `idol_id`, `group_id`, plus base fields
- UI: manager — "this is an album" toggle on the product form, revealing these fields

### `GET /album_details/all` 🔓
- Response: `List[AlbumDetailRead]`
- UI: merch catalog — album-specific badges/filters

### `GET /album_details/{product_id}` 🔓
- Response: `AlbumDetailRead`
- UI: product detail page (album variant)

### `PUT /album_details/update/{product_id}` 🔒 manager+ (company-scoped)
- Request (`AlbumDetailUpdate`): `release_date`, `track_count`, `format`, `cover_image_url`
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

### `DELETE /genres/album_genres/{product_id}/{genre_id}` 🔒 manager+
- Response: `{"msg": "Genre unassigned from album successfully"}`
- UI: album edit page — remove a genre tag

### `POST /lightstick_details/add` 🔒 manager+
Same pattern as album details, for official lightstick merch.
- Request (`LightstickDetailCreate`): `product_id` (uuid), `idol_id` (uuid, optional), `group_id`
  (uuid, optional — exactly one), `edition` (str, optional), `color_id` (uuid, optional — links to
  `idol_colors`)
- Response (`LightstickDetailRead`): adds `created_at`
- UI: manager — "this is a lightstick" toggle on the product form

### `GET /lightstick_details/all` 🔓
- Response: `List[LightstickDetailRead]`

### `GET /lightstick_details/{product_id}` 🔓
- Response: `LightstickDetailRead`
- UI: product detail page (lightstick variant)

### `PUT /lightstick_details/update/{product_id}` 🔒 manager+ (company-scoped)
- Request (`LightstickDetailUpdate`): `edition`, `color_id`

### `DELETE /lightstick_details/delete/{product_id}` 🔒 manager+ (company-scoped)
- Response: `{"msg": "Lightstick details deleted successfully"}`

---

## 6. Shopping — Cart, Shipping, Order, Payment

### `POST /Cart/add_cart` 🔒 fan
- Request (`CartItem`): `product_id` (uuid), `quantity` (int, ≥1)
- Response: not schema-enforced; the raw `Cart` row (`id`, `product_id`, `quantity`, `user_id`,
  `price`, `total_price`) — adding an item already in the cart increments its quantity rather
  than creating a duplicate row
- UI: "Add to cart" button anywhere a product is shown

### `GET /Cart/see_cart` 🔒 fan
- Response: not schema-enforced; `{"items": [Cart...], "total_price": float}`
- UI: cart page / cart drawer

### `DELETE /Cart/delete_cart/{cart_id}` 🔒 fan
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

### `GET /shipping_addresses/fetch_byid/{address_id}` 🔓
- Response: `ShippingAddress`
- UI: address detail/edit form prefill

### `PUT /shipping_addresses/update/{address_id}` 🔒 fan
- Request (`ShippingBase`): same fields as add
- Response: `{"msg": "Address updated successfully"}`

### `DELETE /shipping_addresses/delete/{address_id}` 🔒 fan
- Response: `{"msg": "Address deleted successfully"}`

### `POST /order/checkout` 🔒 fan
Converts the cart into an order and a payment in one call. **Response is payment info, not the
order** — read that carefully when wiring the success screen.
- Request (`PaymentCreate`): `amount` (int — must equal the cart's current total, checked
  server-side), `shipping_address_id` (uuid), `gateway` (`"mock"`, default `"mock"` — the only
  gateway today; real gateway integration is deferred to a later phase),
  `simulate_succ` (bool, optional — forces a mock success/failure)
- Response: not schema-enforced; `{"payment": PaymentResponse}`
- Errors: `404` (empty cart / bad address), `402` (payment failed), `400` (stock/amount mismatch,
  unsupported gateway, or a resale-cap trigger violation) — distinguish these in the UI rather
  than showing one generic "checkout failed"
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
- Response: not schema-enforced; `ShippingStatusResponse`-shaped (`{"status": ...}`)
- UI: order detail page — shipping tracker

### `PATCH /order/update_shipping_status/{order_id}` 🔒 admin
- Request (`ShippingStatus` enum): `"pending" | "processing" | "shipped" | "delivered" |
  "cancelled"`
- Response: `Order`
- UI: admin — fulfillment/shipping dashboard

### `PATCH /payment/status/{order_id}` 🔒 fan
- Response (`PaymentResponse`): `id`, `order_id`, `user_id`, `amount`, `status`
  (`"pending"|"success"|"failed"|"cancelled"`), `payment_gateway` (`"mock"` — the only value
  today), `is_paid`, `pg_order_id`, `pg_payment_id`, `pg_signature`, `created_at`, `updated_at`
- UI: order detail / checkout success page — poll this while waiting on an async gateway

### `PATCH /payment/status/all` 🔒 fan
- Response: `List[PaymentResponse]`
- UI: "My payments" page, if surfaced separately from orders
