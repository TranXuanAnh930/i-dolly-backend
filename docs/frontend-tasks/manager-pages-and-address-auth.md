# Frontend task: send auth on manager settings pages and address lookup

**Backend branch:** `refactor/add-test-coverage` (fixes `docs/bugs.md` #28 and #29).
**Type:** breaking change. Pages that call these endpoints without a token stop working once
this backend is deployed. Ship the frontend change first or together with the backend.
**Reference:** `docs/api-spec.md` has the exact request and response shapes. This file only lists
what changed and what the frontend has to do about it.

## 1. What changed on the backend

### 1a. The six manager settings pages now require login and are company-scoped

| Endpoint | Before | After |
|---|---|---|
| `GET /products/manager-products-page` | public; returned whatever `?company_id=` asked for | 🔒 manager/admin; a manager always gets their own company |
| `GET /products/manager-product-form-page` | public; same | 🔒 manager/admin; own company's products **and** idol/group pickers |
| `GET /idols/manager-idols-page` | public; every company's idols | 🔒 manager/admin; a manager gets their own company's |
| `GET /idols/manager-idol-form-page` | public; every company's idols/groups | 🔒 manager/admin; a manager gets their own company's |
| `GET /groups/manager-groups-page` | public; every company's groups | 🔒 manager/admin; a manager gets their own company's |
| `GET /concerts/manager-events-page` | public; every company's concerts | 🔒 manager/admin; a manager gets their own company's concerts |

The response shapes (field names and types) are **unchanged**. What changed is who can call the
endpoints and which rows come back:

- **Manager:** only their own company's rows. On the products pages this also includes ownerless
  products (no album/merch detail), as before. A `company_id` query param sent by a manager is
  **ignored**.
- **Admin:** every company's rows, as before. On the two products pages an admin can still pass
  `?company_id=` to narrow to one company, or omit it to get everything.
- **Shared reference data stays unfiltered:** `venues` (events page), `colors` (idol form and
  product form), `categories` (product form).
- **New errors:** `401` without a valid token, `403` for a fan account, `429` above
  30 requests/minute per user per endpoint.

### 1b. `GET /shipping_addresses/fetch_byid/{address_id}` now requires login

- It used to return `500` on every call, so the address edit form's prefill has never worked
  against this backend.
- It now needs the fan's access token and returns only the caller's own address. Any other id,
  including one that belongs to another user, returns `404`.
- `PUT /shipping_addresses/update/{id}` and `DELETE /shipping_addresses/delete/{id}` already
  required a token. They now also return `404` for another user's address. Previously they
  succeeded, which was the security bug.

## 2. Frontend tasks

### Task 1: send the access token on the six manager page calls

- Wherever the manager/admin settings screens fetch these endpoints, attach
  `Authorization: Bearer <access_token>`, the same way the calls to `GET /order/manager-orders-page`
  and the manager write endpoints already do. If there is a shared authenticated API client or
  interceptor, route these calls through it instead of a bare `fetch`.
- On `401`, go through the existing refresh flow (`POST /account/refresh` with
  `credentials: "include"`), retry once, and then send the user to login.
- On `403`, the user is logged in but isn't a manager or admin. Redirect away from the manager
  area. These screens shouldn't be reachable for fans at all; check the route guard.
- Don't prefetch or warm these pages before the user has logged in, for example on app start or
  on the public layout. Those calls would now return `401`.

**Screens affected** (from `api-spec.md` §1): manager products table and product create/edit
form, manager idols table and idol create/edit form, manager groups table, and manager concerts
table and concert create form.

### Task 2: remove client-side company filtering for managers

- The server now does the filtering, so any code that filters these responses by the logged-in
  manager's `company_id` can be deleted for the manager role. Leaving it in does no harm, since it
  is a no-op on already-filtered data. Removing it is cleanup, not a requirement for correctness.
- **Keep** the client-side filtering the **admin** forms use to narrow pickers to the company
  chosen in the form. For example, the idol form's group picker filters `groups` by the selected
  `company_id`. Admins still receive every company's rows.
- Stop sending `?company_id=` from manager screens on the two products pages. It's ignored now.
  Admin screens keep sending it when an admin chooses a company.

### Task 3: address edit form prefill

- Call `GET /shipping_addresses/fetch_byid/{address_id}` with the fan's access token.
- Handle `404` as "address not found": for example, go back to the address list and refresh it.
- If the form was working around the broken endpoint, for example by prefilling from the list
  returned by `GET /shipping_addresses/fetch`, either keep that workaround or switch to
  `fetch_byid`. Both work now.

### Task 4: rate-limit handling

These pages are now limited to **30 requests/minute per user per endpoint**. Normal navigation is
far below that, but check that no screen polls them or refetches them in a render loop. On `429`,
the `detail` message says how many seconds to wait; back off instead of retrying immediately.

## 3. Acceptance checklist

Run against a backend built from this branch, with one fan, one admin, and two managers from
different companies (A and B):

- [ ] **Manager A:** products, idols, groups and concerts settings pages load and show only
      company A's rows, plus ownerless products on the products pages.
- [ ] **Manager A:** the product create form's idol and group pickers list only company A's idols
      and groups. The categories and colors pickers are unchanged.
- [ ] **Manager A:** the idol create form's group picker lists only company A's groups.
- [ ] **Manager A:** the concert create form's venue picker still lists every venue.
- [ ] **Admin:** every settings page shows all companies, and choosing a company in the products
      screens narrows the list as before.
- [ ] **Fan:** opening a manager URL directly redirects away; no manager data is shown.
- [ ] **Logged out:** opening a manager URL goes to login; nothing renders from a `401` response.
- [ ] **Expired access token:** the manager pages recover through the refresh flow without a
      visible error.
- [ ] **Fan:** "Edit address" prefills correctly from `fetch_byid`.
- [ ] **Fan:** an address id that isn't theirs (for example, edited in the URL) shows "not found",
      and saving or deleting it is refused.
- [ ] No console errors or unexpected network calls to these endpoints on public pages.

## 4. Out of scope

- `GET /management_companies/all` stays **public** by design. It returns company names for
  pickers.
- The public pages (`/products/store-page`, `/idols/members-page`, `/groups/groups-page`,
  `/concerts/events-page`, and the `*/detail` pages) haven't changed.
