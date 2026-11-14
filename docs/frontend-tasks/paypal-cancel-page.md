# Frontend task: cancel the checkout when the fan backs out on PayPal

English | [日本語](paypal-cancel-page_JP.md)

**Backend change:** `docs/bugs.md` #12 and #27 (branch `fix/release-abandoned-paypal`).
**Type:** not breaking. Without this task the backend still cleans up the abandoned checkout the
next time the fan checks out; this makes the cancel immediate and the page's wording accurate.
**Reference:** `docs/api-spec.md` §6, the PayPal flow (steps 6 and 7) and
`POST /payment/paypal/cancel/{pg_order_id}`. File names below are in `i-dolly-frontend`.

## 1. What changed on the backend

- New `POST /payment/paypal/cancel/{pg_order_id}`, fan only. It cancels the caller's pending PayPal
  payment and what it was for: a direct-sale ticket becomes `cancelled`, an order becomes
  `cancelled` with shipping status `cancelled`. A lottery win's ticket stays `pending_payment`
  until its deadline. Answers `PaymentResponse` (`status: "cancelled"`), or `404` when the payment
  doesn't exist, isn't the caller's, or was already captured or cancelled.
- A fan's next checkout also cancels their own pending PayPal checkout (same concert for tickets,
  any pending order for the marketplace). Nothing to do in the frontend for that.

## 2. Frontend tasks

### Task 1: call the endpoint from the cancel page

`src/pages/payment/PaypalCancelPage.vue` is purely informational today. PayPal sends the fan back
to it with `?token=<PayPal order id>`, the same `token` the return page passes to capture.

- Add `PaymentService.cancelPaypal(pgOrderId)` in `src/services/payment/payment.service.js`, next
  to `capturePaypal`: `POST payment/paypal/cancel/{pgOrderId}` with auth.
- In the page's `created()`, read `this.$route.query.token` (as `PaypalReturnPage.vue` does) and
  call it. Treat `404` as success: the checkout was already resolved, for example by a later
  checkout in another tab. Show the page either way; on a network error, still show it.

### Task 2: update the wording

`paypalCancel.note` in `src/i18n/locales/en.js` and `ja.js` says the order "is saved as pending".
It's now cancelled. Suggested English: "You cancelled before approving on PayPal, so nothing was
charged and this checkout was cancelled. You can start over at any time." For a lottery win the
ticket stays reserved until its deadline; if the page can tell (it can't today), say so instead.

## 3. Acceptance checklist

- [ ] Start a PayPal ticket checkout, click "Cancel and return" on PayPal: the cancel page loads,
      the network tab shows `POST /payment/paypal/cancel/...` answering 200, and History shows the
      ticket as cancelled.
- [ ] Right after that, buying a ticket for the same concert works.
- [ ] Same for a marketplace order: it shows as cancelled in History.
- [ ] Opening the cancel page a second time (reload) shows the page normally; the 404 isn't
      shown as an error.
- [ ] Without cancelling, closing the PayPal tab and buying again for the same concert works.

## 4. Out of scope

- Pending checkouts left by a fan who never comes back still show as pending in History.
- Unpaid lottery wins are unchanged.
