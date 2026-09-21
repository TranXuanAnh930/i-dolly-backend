from enum import Enum


class EmailTemplate(Enum):
    """Subject + body template for every transactional email this app sends. `render()` fills
    in the body's placeholders; the task name each is dispatched under stays at the call site.

    Bodies are HTML — app/utils/email_sender.py sends them under Resend's `html` param, and a
    plain-text body sent that way loses its line breaks (HTML collapses bare `\\n`s to spaces).
    Every placeholder here is either an EmailStr validated at the schema boundary (`{email}`) or a
    server-generated value (ids, prices, an HMAC-signed `{link}` token) — none are arbitrary user
    text, so interpolating straight into HTML doesn't need escaping.
    """

    EMAIL_VERIFICATION = (
        "Verify your email",
        "<p>Hi {email},</p>"
        "<p>Please verify your email address by clicking the link below:</p>"
        '<p><a href="{link}">{link}</a></p>'
        "<p>This link expires shortly, so verify soon.<br>"
        "If you didn't request this, you can ignore this email.</p>",
    )
    ORDER_PLACED = (
        "Your order has been placed",
        "<p>Hi {email},</p>"
        "<p>Your order has been placed successfully.</p>"
        "<p>Order ID: {order_id}<br>"
        "Total: ${total:.2f}<br>"
        "Status: {status}</p>"
        "<p>You can track its status from your account's order history.</p>",
    )
    TICKET_CONFIRMED = (
        "Your ticket has been confirmed",
        "<p>Hi {email},</p>"
        "<p>Your ticket has been confirmed.</p>"
        "<p>Ticket ID: {ticket_id}<br>"
        "Tier: {tier}<br>"
        "Price: ${price:.2f}</p>"
        "<p>Bring this confirmation with you to the venue.</p>",
    )
    LOTTERY_WON = (
        "You won the lottery!",
        "<p>Hi,</p>"
        "<p>You won the lottery for a {tier} ticket.</p>"
        "<p>Ticket ID: {ticket_id}<br>"
        "Price: ${price:.2f}<br>"
        "Pay before: {deadline}</p>"
        "<p>Complete payment before the deadline or the seat will be released to someone else.</p>",
    )
    LOTTERY_LOST = (
        "Lottery result",
        "<p>Hi,</p>"
        "<p>The lottery draw has concluded and you weren't selected this time.</p>"
        "<p>Keep an eye out for future ticket sales and lottery campaigns.</p>",
    )
    LOTTERY_PAYMENT_CONFIRMED = (
        "Your ticket payment is confirmed",
        "<p>Hi {email},</p>"
        "<p>Your payment for your lottery-won ticket has been confirmed.</p>"
        "<p>Ticket ID: {ticket_id}<br>"
        "Tier: {tier}<br>"
        "Price: ${price:.2f}</p>"
        "<p>Bring this confirmation with you to the venue.</p>",
    )
    RESET_PASSWORD = (
        "Reset your password",
        "<p>Hi {email},</p>"
        "<p>We received a request to reset your password. If you didn't make this request, you "
        "can ignore this email.</p>"
        "<p>Click the link below to choose a new password:</p>"
        '<p><a href="{link}">{link}</a></p>'
        "<p>This link expires in 15 minutes.</p>",
    )

    @property
    def subject(self) -> str:
        return self.value[0]

    def render(self, **fields: object) -> str:
        return self.value[1].format(**fields)
