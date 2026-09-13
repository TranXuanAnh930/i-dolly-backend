# Japan's standard consumption tax rate — mirrors src/utils/tax.js on the
# frontend. cart/product prices are stored tax-excluded, same as the rest of
# the store, so checkout applies tax to each cart row's total here.
TAX_RATE = 0.1


def with_tax(amount: float) -> int:
    # int(x + 0.5) matches JS's Math.round for positive values (round half
    # up), unlike Python's built-in round() (round half to even) — checkout
    # requires the frontend-computed amount to match this exactly, so both
    # sides must round the same way.
    return int(amount * (1 + TAX_RATE) + 0.5)
