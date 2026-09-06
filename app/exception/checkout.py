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