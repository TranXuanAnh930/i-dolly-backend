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
    """No such ticket, or it exists but doesn't belong to the caller —
    collapsed into one case so a payment attempt on someone else's ticket
    id doesn't confirm the id exists."""
    pass

class TicketNotPayableError(CartItemError):
    """The ticket isn't a pending lottery win: never won one (no
    lottery_entry_id), already resolved (paid/cancelled/expired), or its
    payment_deadline_at has just lapsed."""
    pass