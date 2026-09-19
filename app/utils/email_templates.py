from enum import Enum


class EmailTemplate(Enum):
    """Subject + body template for every transactional email this app sends. `render()` fills
    in the body's placeholders; the task name each is dispatched under stays at the call site."""

    EMAIL_VERIFICATION = (
        "Verify your email",
        "Hi {email},\n\n"
        "Please verify your email address by clicking the link below:\n\n"
        "{link}\n\n"
        "This link expires shortly, so verify soon.\n"
        "If you didn't request this, you can ignore this email.",
    )
    ORDER_PLACED = (
        "Your order has been placed",
        "Hi {email},\n\n"
        "Your order has been placed successfully.\n\n"
        "Order ID: {order_id}\n"
        "Total: ${total:.2f}\n"
        "Status: {status}\n\n"
        "You can track its status from your account's order history.",
    )
    TICKET_CONFIRMED = (
        "Your ticket has been confirmed",
        "Hi {email},\n\n"
        "Your ticket has been confirmed.\n\n"
        "Ticket ID: {ticket_id}\n"
        "Tier: {tier}\n"
        "Price: ${price:.2f}\n\n"
        "Bring this confirmation with you to the venue.",
    )
    LOTTERY_WON = (
        "You won the lottery!",
        "Hi,\n\n"
        "You won the lottery for a {tier} ticket.\n\n"
        "Ticket ID: {ticket_id}\n"
        "Price: ${price:.2f}\n"
        "Pay before: {deadline}\n\n"
        "Complete payment before the deadline or the seat will be released to someone else.",
    )
    LOTTERY_LOST = (
        "Lottery result",
        "Hi,\n\n"
        "The lottery draw has concluded and you weren't selected this time.\n\n"
        "Keep an eye out for future ticket sales and lottery campaigns.",
    )
    LOTTERY_PAYMENT_CONFIRMED = (
        "Your ticket payment is confirmed",
        "Hi {email},\n\n"
        "Your payment for your lottery-won ticket has been confirmed.\n\n"
        "Ticket ID: {ticket_id}\n"
        "Tier: {tier}\n"
        "Price: ${price:.2f}\n\n"
        "Bring this confirmation with you to the venue.",
    )

    @property
    def subject(self) -> str:
        return self.value[0]

    def render(self, **fields: object) -> str:
        return self.value[1].format(**fields)
