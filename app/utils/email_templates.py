from enum import Enum


class EmailTemplate(Enum):
    """Subject and HTML body template for each transactional email; render() fills placeholders.

    Placeholders are validated emails or server-generated values (ids, prices, signed links), so
    they're interpolated without HTML escaping.
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
        "Total: ¥{total:,.0f} (tax included)<br>"
        "Payment: {payment_status}</p>"
        "<p>You can track its status from your account's order history.</p>",
    )
    TICKET_CONFIRMED = (
        "Your ticket has been confirmed",
        "<p>Hi {email},</p>"
        "<p>Your ticket has been confirmed.</p>"
        "<p>Ticket ID: {ticket_id}<br>"
        "Tier: {tier}<br>"
        "Price: ¥{price:,.0f} (tax included)</p>"
        "<p>Bring this confirmation with you to the venue.</p>",
    )
    LOTTERY_PAYMENT_CONFIRMED = (
        "Your ticket payment is confirmed",
        "<p>Hi {email},</p>"
        "<p>Your payment for your lottery-won ticket has been confirmed.</p>"
        "<p>Ticket ID: {ticket_id}<br>"
        "Tier: {tier}<br>"
        "Price: ¥{price:,.0f} (tax included)</p>"
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
    # Deliberately omits the user's own text: echoing it would let anyone send arbitrary content
    # from our address to any inbox they type in.
    INQUIRY_RECEIVED = (
        "We've received your inquiry",
        "<p>Hi {email},</p>"
        "<p>Thank you for contacting us. We've received your inquiry and will reply to this "
        "address as soon as we can.</p>"
        "<p>Reference: {inquiry_id}<br>"
        "Topic: {topic}</p>"
        "<p>If you didn't send this, you can ignore this email.</p>",
    )

    @property
    def subject(self) -> str:
        return self.value[0]

    def render(self, **fields: object) -> str:
        return self.value[1].format(**fields)
