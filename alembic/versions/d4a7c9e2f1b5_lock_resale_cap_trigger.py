"""serialize fn_enforce_resale_cap per (buyer, product)

Revision ID: d4a7c9e2f1b5
Revises: b8e2d4f6a1c3
Create Date: 2026-09-30 00:00:00.000000

The trigger summed the buyer's existing units of the product and then let the insert through.
Under READ COMMITTED two concurrent inserts for the same buyer and product can't see each other's
uncommitted row, so both passed and the buyer ended up past the cap. A transaction-scoped advisory
lock on (buyer, product), taken before the sum, makes the second insert wait for the first to
commit; the sum then sees the committed line and raises.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4a7c9e2f1b5'
down_revision: Union[str, Sequence[str], None] = 'b8e2d4f6a1c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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

            -- Held until commit; a hash collision only serializes unrelated inserts.
            PERFORM pg_advisory_xact_lock(
                hashtextextended(buyer_id::text || ':' || NEW.product_id::text, 0)
            );

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


def downgrade() -> None:
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
