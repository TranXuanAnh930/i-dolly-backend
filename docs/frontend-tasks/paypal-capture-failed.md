# Frontend task: a failed PayPal capture now also releases the ticket or order

English | [日本語](paypal-capture-failed_JP.md)

**Backend change:** `docs/bugs.md` #31 and #33 (branch `fix/paypal-unavailable-capture`).
**Type:** not breaking. Without this task a fan sees correct text on the return page, but their
History can show a stale "pending" for an order or ticket the backend has already cancelled.
**Reference:** `docs/api-spec.md` §6, the PayPal flow, step 5. File names are in `i-dolly-frontend`.

## 1. What changed on the backend

`POST /payment/paypal/capture/{pg_order_id}` used to answer `404` when, after the fan approved on
PayPal, the ticket tier had sold out or the product was short on stock, and the ticket or order
stayed `pending`. A product taken off sale in between was captured anyway.

Now, in all three cases, the backend captures nothing (no money moves), cancels the ticket or order,
and answers **200 with `status: "failed"`**, the same shape as a declined capture. There is no
reason field, so "sold out" and "declined" look the same.

## 2. Frontend tasks

### Task 1: refresh History after a failed capture

`src/pages/payment/PaypalReturnPage.vue` refetches the orders and tickets stores (`force: true`) only
when `payment.status === 'success'`. A failed capture now changes the order or ticket too (it becomes
`cancelled`), so refetch on `failed` as well; otherwise History and "View details" keep showing the
pre-payment `pending` snapshot until a full reload.

### Task 2 (optional): wording

`paypalReturn.failedNote` says PayPal "didn't confirm this payment — nothing was charged." That stays
true. Consider adding that the item may no longer be available, for example: "PayPal didn't confirm
this payment, or the item is no longer available. Nothing was charged." Both locale files
(`en.js`, `ja.js`).

## 3. Acceptance checklist

- [ ] Start a PayPal order, reduce the product's stock below the order's quantity in the database,
      then complete PayPal approval: the return page shows the failed state, History shows the
      order as cancelled, and PayPal shows no charge.
- [ ] Same with the product deactivated from the manager page after the order was started.
- [ ] A normal PayPal order and ticket still end as successful.

## 4. Out of scope

- A reason code in the response (to tell "sold out" from "declined") is not built.
