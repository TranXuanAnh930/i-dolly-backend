from app.exception.common import CodedError


class CartItemError(CodedError):
    code = "checkout_error"

class InsufficientStockError(CartItemError):
    code = "insufficient_stock"

class PaymentAmountMismatch(CartItemError):
    code = "amount_mismatch"

class AddressIdError(CartItemError):
    code = "address_not_found"

class UnsupportedGatewayError(CartItemError):
    code = "unsupported_gateway"

class TicketTypeNotFoundError(CartItemError):
    code = "ticket_type_not_found"

class WrongSaleMethodError(CartItemError):
    code = "wrong_sale_method"

class InsufficientTicketStockError(CartItemError):
    code = "sold_out"

class NotOnSaleError(CartItemError):
    code = "not_on_sale"

class LotteryEntryUnresolvedError(CartItemError):
    code = "lottery_entry_unresolved"

class TicketNotFoundError(CartItemError):
    """Ticket missing or not the caller's (one error, so ids of other users' tickets aren't confirmed)."""
    code = "ticket_not_found"

class TicketNotPayableError(CartItemError):
    """The ticket isn't an unpaid lottery win, or its payment deadline has passed."""
    code = "ticket_not_payable"
