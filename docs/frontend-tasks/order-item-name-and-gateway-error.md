# Frontend task: order item names and the PayPal gateway error

English | [日本語](order-item-name-and-gateway-error_JP.md)

**Backend change:** `docs/bugs.md` #34, #35 and #36. None is breaking.
**Reply to:** `docs/backend-tasks/live-e2e-findings.md` items 1–3.

## 1. `product_name` on every order item

`GET /order/fetch_placed_order`, `GET /order/single_placed_order/{id}` and the `Order` returned by
`POST /order/checkout` now have `items[].product_name`, also for a deactivated product.

- `OrderDetailsPage.vue`: show `item.product_name`, falling back to the catalog lookup only if it is
  missing. This removes "Unknown product" for deactivated products.
- The live e2e test that annotates `[known-gap]` can now assert the name.
- No image field was added; a past order still has no cover for a deactivated product.

## 2. PayPal unavailable at checkout

`POST /order/checkout`, `POST /tickets/checkout` and `POST /tickets/{id}/checkout` with
`gateway: "paypal"` answer **502** `{"detail": ..., "code": "payment_gateway_unavailable"}` when
PayPal can't be reached or rejects the request. Nothing was created: the cart, stock and ticket are
unchanged, so the fan can try again.

- Show a message such as "PayPal isn't responding right now. Your cart is unchanged; please try
  again." for this code, in both locales.
- The capture endpoint and the webhook are not covered; they can still answer a bare 500.

## 3. Forgot-password: the per-email message now shows

The per-IP limit on `POST /profile/forgot-password` is 8/min (was 3/min), above the per-email
limit of 3/hour. A user retrying from one network now gets `too_many_reset_requests` on the 4th
request, so the message you added is reachable. Nothing to change; the live test no longer needs
to clear the `rate:ip:*` keys to reach it.
