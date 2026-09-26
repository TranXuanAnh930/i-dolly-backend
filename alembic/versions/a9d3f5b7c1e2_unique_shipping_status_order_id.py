"""unique shipping_status.order_id

Revision ID: a9d3f5b7c1e2
Revises: f1a7c3e9b5d2
Create Date: 2026-09-24 00:00:00.000000

Order.shippingstatus is a uselist=False relationship, but nothing stopped more than one
shipping_status row per order: PaymentService.create_payment inserted one at checkout and
finalize_paypal_payment inserted another on capture (docs/bugs.md #1). With two rows, which one
loaded was arbitrary — a declined order could read as "pending" and be shipped.

No dedupe step: no orders were created while the duplicate-row code was live, so there's nothing
to clean up. If a database does turn out to hold duplicates, ADD CONSTRAINT fails loudly here
rather than silently deleting rows.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a9d3f5b7c1e2'
down_revision: Union[str, Sequence[str], None] = 'f1a7c3e9b5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint("uq_shipping_status_order_id", "shipping_status", ["order_id"])


def downgrade() -> None:
    op.drop_constraint("uq_shipping_status_order_id", "shipping_status", type_="unique")
