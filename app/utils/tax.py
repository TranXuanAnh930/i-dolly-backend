# Japan's consumption tax. Prices are stored tax-exclusive; must match the frontend's tax.js.
TAX_RATE = 0.1


def with_tax(amount: float) -> int:
    # Round half up like JS Math.round (Python's round() rounds half to even), so the amount matches
    # the frontend's exactly.
    return int(amount * (1 + TAX_RATE) + 0.5)
