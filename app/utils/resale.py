# Anti-resale purchase limit — applies per product, per user, cumulative
# across every order they've ever placed (see order_service.checkout and
# database-design.md §4.2), to any product whose category has
# is_resale_capped=True (the default — see Category.is_resale_capped).
# One named constant so the number product_service exposes to the client
# can never drift from the number order_service actually enforces.
RESALE_CAP_QUANTITY = 3
