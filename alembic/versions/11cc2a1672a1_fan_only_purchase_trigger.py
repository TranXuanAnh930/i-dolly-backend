"""fan-only purchase trigger on cart/orders/lottery_entries/tickets

Revision ID: 11cc2a1672a1
Revises: e42a17b5f4ca
Create Date: 2026-09-04 15:03:30.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '11cc2a1672a1'
down_revision: Union[str, Sequence[str], None] = 'e42a17b5f4ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# admin/manager accounts never participate in purchase activity
# (database-design.md §4.1). Enforced at TWO layers, deliberately: a service-
# layer role check (cart_service/order_service/the lottery services), and
# this DB-level trigger as a hard backstop — money movement, so a missed
# service-layer check on a new endpoint shouldn't be enough to let an admin/
# manager account buy something. `cart` and `orders` already exist in the
# live codebase — this attaches to them, it doesn't recreate them.


def upgrade() -> None:
    op.execute(sa.text(
        """
        CREATE OR REPLACE FUNCTION fn_enforce_fan_only_purchase() RETURNS TRIGGER AS $$
        DECLARE
            buyer_role user_role_enum;
        BEGIN
            SELECT role INTO buyer_role FROM users WHERE id = NEW.user_id;
            IF buyer_role IS DISTINCT FROM 'fan' THEN
                RAISE EXCEPTION 'admin/manager accounts cannot participate in purchase activity (user_id=%, role=%)',
                    NEW.user_id, buyer_role;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    ))
    op.execute(sa.text(
        """
        CREATE TRIGGER trg_cart_fan_only
            BEFORE INSERT ON cart
            FOR EACH ROW EXECUTE FUNCTION fn_enforce_fan_only_purchase();
        """
    ))
    op.execute(sa.text(
        """
        CREATE TRIGGER trg_orders_fan_only
            BEFORE INSERT ON orders
            FOR EACH ROW EXECUTE FUNCTION fn_enforce_fan_only_purchase();
        """
    ))
    op.execute(sa.text(
        """
        CREATE TRIGGER trg_lottery_entries_fan_only
            BEFORE INSERT ON lottery_entries
            FOR EACH ROW EXECUTE FUNCTION fn_enforce_fan_only_purchase();
        """
    ))
    op.execute(sa.text(
        """
        CREATE TRIGGER trg_tickets_fan_only
            BEFORE INSERT ON tickets
            FOR EACH ROW EXECUTE FUNCTION fn_enforce_fan_only_purchase();
        """
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_tickets_fan_only ON tickets"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_lottery_entries_fan_only ON lottery_entries"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_orders_fan_only ON orders"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_cart_fan_only ON cart"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_enforce_fan_only_purchase()"))
