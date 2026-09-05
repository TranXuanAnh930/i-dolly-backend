"""anti-resale cap trigger on orders_items

Revision ID: 7abe0b6123b3
Revises: 11cc2a1672a1
Create Date: 2026-09-04 15:03:45.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7abe0b6123b3'
down_revision: Union[str, Sequence[str], None] = '11cc2a1672a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Hard cap: at most 3 units of the SAME product per user, lifetime, summed
# across ALL their orders — independent of any lottery campaign
# (database-design.md §4.2). Reads categories.is_resale_capped (added by
# 67536a8e127a) rather than hardcoding a category list — data-driven, so
# exempting a category later is an UPDATE, not a code change. `orders_items`
# already exists in the live codebase — this attaches to it, it doesn't
# recreate it.


def upgrade() -> None:
    op.execute(sa.text(
        """
        CREATE OR REPLACE FUNCTION fn_enforce_resale_cap() RETURNS TRIGGER AS $$
        DECLARE
            buyer_id UUID;
            is_capped BOOLEAN;
            existing_qty INTEGER;
        BEGIN
            SELECT COALESCE(c.is_resale_capped, false) INTO is_capped
            FROM products p
            LEFT JOIN categories c ON c.id = p.category_id
            WHERE p.id = NEW.product_id;

            IF NOT is_capped THEN
                RETURN NEW;
            END IF;

            SELECT user_id INTO buyer_id FROM orders WHERE id = NEW.order_id;

            SELECT COALESCE(SUM(oi.quantity), 0) INTO existing_qty
            FROM orders_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE o.user_id = buyer_id AND oi.product_id = NEW.product_id;

            IF existing_qty + NEW.quantity > 3 THEN
                RAISE EXCEPTION 'user_id=% would exceed the 3-unit anti-resale cap on product_id=% (existing=%, requested=%)',
                    buyer_id, NEW.product_id, existing_qty, NEW.quantity;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    ))
    op.execute(sa.text(
        """
        CREATE TRIGGER trg_orders_items_resale_cap
            BEFORE INSERT ON orders_items
            FOR EACH ROW EXECUTE FUNCTION fn_enforce_resale_cap();
        """
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_orders_items_resale_cap ON orders_items"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_enforce_resale_cap()"))
