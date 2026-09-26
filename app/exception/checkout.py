class CartItemError(Exception):
    pass

class PaymentFailedError(CartItemError):
    pass

class PaymentError(CartItemError):
    pass

class OrderError(CartItemError):
    pass

class InsufficientStockError(CartItemError):
    pass

class PaymentAmountMismatch(CartItemError):
    pass

class AddressIdError(CartItemError):
    pass

class UnsupportedGatewayError(CartItemError):
    pass

class TicketTypeNotFoundError(CartItemError):
    pass

class WrongSaleMethodError(CartItemError):
    pass

class InsufficientTicketStockError(CartItemError):
    pass

class NotOnSaleError(CartItemError):
    pass

class LotteryEntryUnresolvedError(CartItemError):
    pass

class TicketNotFoundError(CartItemError):
    """Ticket missing or not the caller's (one error, so ids of other users' tickets aren't confirmed)."""
    pass

class TicketNotPayableError(CartItemError):
    """The ticket isn't an unpaid lottery win, or its payment deadline has passed."""
    pass