# Frontend task: per-account limit messages and the Ship button on unpaid orders

English | [日本語](auth-limits-and-unpaid-orders_JP.md)

**Backend changes:** `docs/bugs.md` #7 (merged and deployed, release 1.4.2), and #26 and #14
(branch `fix/ship-unpaid-and-cancel-route`).
**Type:** not breaking. The frontend keeps working without any of this; each task replaces a
generic message or a misleading button with the right one, so they can ship after the backend.
**Reference:** `docs/api-spec.md` has the exact request and response shapes. This file only lists
what changed and what the frontend has to do about it. File names below are in `i-dolly-frontend`.

## 1. What changed on the backend

### 1a. Login and forgot-password have a per-email limit (#7)

On top of the existing per-IP limits, two routes now count per email address:

| Endpoint | Limit | Over the limit |
|---|---|---|
| `POST /account/login` | 5 **failed** attempts per email per 15 minutes; a successful login resets the count | `429`, code `too_many_login_attempts` |
| `POST /profile/forgot-password` | 3 requests per email per hour | `429`, code `too_many_reset_requests` |

- While an email is over the login limit, **every** login for it returns the 429, including one
  with the correct password. It clears by itself when the 15-minute window ends.
- Both limits count unregistered emails the same way, so the response says nothing about whether
  an account exists. Don't word the message as if it does.
- Unlike the per-IP 429 (code `rate_limited`, `detail` "…try again after N seconds"), these two
  have **no seconds in `detail`**. `ApiError.retryAfter` is `null` for them.

### 1b. Shipping needs a paid order (#26)

| Endpoint | Before | After |
|---|---|---|
| `PATCH /order/{order_id}/ship` | shipped any order whose shipping status was `pending`/`processing` | also requires the order's `status` to be `"confirmed"`; otherwise `400`, code `order_not_paid` |
| `PATCH /order/update_shipping_status/{order_id}` (admin) | set any status | `400 order_not_paid` on an order that isn't `confirmed`, unless the new status is `"cancelled"` |

Why it matters: a PayPal order gets a `pending` shipping status at checkout, before the payment is
captured. An abandoned PayPal checkout therefore shows up on the manager orders page with order
`status: "pending"` and a shippable-looking shipping status. `GET /order/manager-orders-page` is
unchanged and already returns each order's `status`.

### 1c. `PATCH /order/cancel/{order_id}` is gone (#14)

The route is no longer registered and now returns `404`. Nothing in the frontend calls it today
(`src/services/store/order.service.js` has no cancel method), so there is nothing to remove. Don't
add a "cancel order" button against it: order cancellation isn't supported until the backend
implements refund and restock.

## 2. Frontend tasks

### Task 1: translate the two new 429 codes

Today neither code has a translation, so `ApiError.message` (`src/services/apiError.js`) falls
back to `errors.rate_limited_generic`: "Too many attempts. Please wait a moment and try again."
That is safe but vague: "a moment" can be up to 15 minutes or an hour.

- Add `errors.too_many_login_attempts` and `errors.too_many_reset_requests` to
  `src/i18n/locales/en.js` and `ja.js`. Suggested English:
  - `too_many_login_attempts`: "Too many failed login attempts for this email. Try again in
    15 minutes, or reset your password."
  - `too_many_reset_requests`: "Too many reset requests for this email. Try again in an hour, and
    check your inbox for a link already sent."
- No change is needed in `apiError.js`: once the key exists, `message` uses it.

### Task 2: login page behaviour for `too_many_login_attempts`

`src/pages/auth/Login.vue` treats `rate_limited` specially (countdown, submit blocked) and
`invalid_credentials` specially (fields turn red).

- `too_many_login_attempts` should be neither: no countdown (there are no seconds to count), and
  don't mark the fields red, since the password may well be correct.
- Show the translated message, with a link to the forgot-password page next to it.
- Keep clearing the error when the fan edits the email: a different email has its own count.

`src/pages/auth/ForgotPasswordPage.vue` already shows `error.message`, so Task 1 is all it needs.

### Task 3: show "Ship" only for paid orders

In `src/pages/manager/ManagerOrdersPage.vue`:

- `canShip(order)` checks only the shipping status. Add `order.status === 'confirmed'`.
- Add `errors.order_not_paid` to both locale files, for the case where the button was shown from
  stale data (for example the list was loaded before a status change). Suggested English: "This
  order hasn't been paid, so it can't be shipped."
- Optional: make unpaid orders easier to tell apart in the list. They already render a status
  badge from `order.status`; a `pending` order with no Ship button is an unpaid or abandoned
  PayPal checkout, not something waiting on the manager.

If there is an admin screen for `PATCH /order/update_shipping_status`, apply the same rule there:
for an order that isn't `confirmed`, offer only `cancelled`.

## 3. Acceptance checklist

Run against a backend that includes both changes. PayPal sandbox is needed for the unpaid-order
checks; otherwise set an order's `status` to `pending` directly in the database.

- [ ] **Login:** 5 wrong passwords for one email, then a 6th attempt, shows the new login message,
      not the generic one, in both English and Japanese.
- [ ] **Login:** in that state the fields aren't red, there is no countdown, and the
      forgot-password link is visible.
- [ ] **Login:** the correct password for that email is also refused until the window ends, with
      the same message.
- [ ] **Login:** a different email can still log in from the same browser.
- [ ] **Login:** the per-IP limit (11 quick attempts with different emails) still shows the
      countdown as before.
- [ ] **Forgot password:** the 4th request for one email within an hour shows the new reset
      message.
- [ ] **Manager orders:** a `confirmed` order with shipping status `pending` or `processing` shows
      Ship, and shipping it works as before.
- [ ] **Manager orders:** an order with `status: "pending"` (PayPal checkout started, never
      approved) shows no Ship button.
- [ ] **Manager orders:** a `cancelled` order shows no Ship button.
- [ ] **Manager orders:** forcing the call on an unpaid order (for example from a stale tab) shows
      the `order_not_paid` message as a toast, and the row doesn't change.
- [ ] No screen offers "cancel order".

## 4. Out of scope

- The per-IP limits and their countdown haven't changed.
- Abandoned PayPal orders still stay `pending` forever and still appear in the fan's order history
  and on the manager orders page (`docs/bugs.md` #27). Hiding or expiring them is a later backend
  change; don't filter them out client-side.
- Order cancellation by the fan (`docs/bugs.md` #14) is not built.
