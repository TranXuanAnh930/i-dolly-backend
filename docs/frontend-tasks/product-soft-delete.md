# Frontend task: products are deactivated, not deleted

English | [日本語](product-soft-delete_JP.md)

**Backend change:** `docs/bugs.md` #2 (branch `fix/product-soft-delete`).
**Type:** not breaking. Existing calls keep working, but "delete" now means "deactivate", and the
manager and admin screens don't show that state or offer a way back yet.
**Reference:** `docs/api-spec.md` has the exact request and response shapes. This file only lists
what changed and what the frontend has to do about it. File names below are in `i-dolly-frontend`.

## 1. What changed on the backend

### 1a. Deleting a product is a soft delete

| Endpoint | Before | After |
|---|---|---|
| `DELETE /products/delete/{id}` | removed the row, and with it the product's lines in every past order | sets `is_active = false`; the row and all order history stay |
| `PATCH /products/activate/{id}` | didn't exist | sets `is_active = true` again; manager/admin, same company scoping as update; `404` unknown id, `403` another company's product |

This is the same model groups and idols already use (`DELETE /groups/delete/{id}` +
`PATCH /groups/activate/{id}`).

A deactivated product:

- is gone from every fan-facing read: `GET /products/store-page`, `/products/all`, `/search`,
  `/filter`, `/pagination`, the recommendations on other product pages, and the product list on a
  group detail page;
- returns `404` from its own `GET /products/{id}/detail`;
- is removed from every fan's cart at the moment it is deactivated, and `POST /cart/add_cart`
  returns `404` for it;
- still appears in past orders, with its name and price, and its sales page still works.

Reactivating brings it back to the store. It does **not** put it back in the carts it was removed
from.

### 1b. Manager pages list deactivated products, with a flag

`GET /products/manager-products-page` and `GET /products/manager-product-form-page` now return
`is_active` (bool) on every product row, and include deactivated products. Edit and image upload
still work on a deactivated product.

### 1c. Two new error codes

| Code | Status | Where |
|---|---|---|
| `product_unavailable` | 400 | `POST /order/checkout` when the cart still holds a deactivated product. Rare: only if the product was deactivated in the instant between loading the cart and paying |
| `category_in_use` | 400 | `DELETE /categories/delete/{id}` (admin) while the category has any product, deactivated ones included |

## 2. Frontend tasks

### Task 1: manager products page — show the state, add deactivate and reactivate

`src/pages/manager/ManagerProductsPage.vue` has no delete action today (it was removed because the
old hard delete wiped sales history; see the comment in `src/services/store/products.service.js`).
That reason is gone, so bring the action back in its safe form. `ManagerGroupsPage.vue` is the
model to copy:

- Row class `is-inactive` and a status badge from `product.is_active`
  (`common.statusActive` / `common.statusInactive` already exist).
- A **Deactivate** button on active rows → `DELETE /products/delete/{id}`, and a **Reactivate**
  button on inactive rows → `PATCH /products/activate/{id}` (`common.deactivate` /
  `common.reactivate` already exist).
- Add `ProductsService.deactivate(id)` and `ProductsService.reactivate(id)`, through the staff
  request path like the other manager calls.
- Confirm text for deactivate should say what happens: it leaves the store and fans' carts, and
  order history is kept.
- Refresh the list after either action.

### Task 2: admin products page — relabel "delete"

`src/pages/admin/AdminProductsPage.vue` calls `ProductsService.remove(product.id)` behind a
"confirm delete" dialog. The call still works, but the product no longer disappears from the list:
it comes back with `is_active: false`. Apply the same changes as Task 1 (badge, Deactivate /
Reactivate, accurate confirm text) so the row doesn't look like the delete failed.

### Task 3: product edit form

The edit form loads its product from `manager-product-form-page`, which includes deactivated
products, so editing one keeps working. Show the inactive state on the form (a badge or a note),
so a manager doesn't expect their edit to appear in the store.

### Task 4: fan-facing handling

- **Product detail page:** a `404` now also means "this product was taken off sale". If a fan
  follows an old link (order history, a bookmark), show the existing not-found state rather than
  an error toast, with a link back to the store.
- **Order history and order detail:** if order lines link to the product page, the link can now
  lead to that 404. Either keep the link and rely on the not-found page, or render the name as
  plain text when the product isn't in the store data you already have.
- **Cart:** an item can disappear from the cart between visits. Nothing breaks, since
  `GET /cart/see_cart` just returns fewer rows, but don't keep rendering a locally cached cart
  after a refetch.
- **Checkout:** add `errors.product_unavailable` to `src/i18n/locales/en.js` and `ja.js`.
  Suggested English: "An item in your cart is no longer available. Review your cart and try
  again." On this error, refetch the cart.

### Task 5: category delete (admin), if a screen exists for it

Add `errors.category_in_use`. Suggested English: "This category still has products. Move or
remove them before deleting it." Note that deactivated products count, so "remove" isn't possible
from the UI today; the practical path is moving the products to another category.

## 3. Acceptance checklist

- [ ] **Manager:** deactivating a product shows it as inactive in the list straight away, with a
      Reactivate button.
- [ ] **Manager:** the deactivated product is gone from the public store page and its detail URL
      shows not-found.
- [ ] **Manager:** its sales page still lists past sales.
- [ ] **Manager:** reactivating returns it to the store; another company's manager can't
      reactivate it.
- [ ] **Admin:** the admin products page shows the same state and actions, and no "delete" wording
      remains.
- [ ] **Fan:** an order containing a since-deactivated product still shows that line, name and
      price intact.
- [ ] **Fan:** a product in the cart that gets deactivated is gone from the cart on next load, and
      the cart total updates.
- [ ] **Fan:** "Add to cart" on a stale page for a deactivated product shows a sensible
      not-found message.
- [ ] **Edit form:** a deactivated product opens, saves, and shows that it is inactive.
- [ ] Both locales have the new strings.

## 4. Out of scope

- There is no hard delete, even for a product that was never ordered.
- A PayPal order that is still pending when its product is deactivated can still be paid
  (`docs/bugs.md` #33). No frontend handling is needed.
- Categories have no soft delete; a category can only be deleted once it has no products.
