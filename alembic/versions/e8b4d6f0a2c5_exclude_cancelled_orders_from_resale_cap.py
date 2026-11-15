"""exclude cancelled orders from fn_enforce_resale_cap

Revision ID: e8b4d6f0a2c5
Revises: c5e9a3b7d1f6
Create Date: 2026-11-15 00:00:00.000000

The trigger summed a buyer's units of a product over every order, whatever its status, so a
cancelled order (a declined payment, an abandoned PayPal checkout the next checkout cancelled)
kept using up the 3-unit cap. It now counts only orders that still stand: confirmed, and pending
(a pending PayPal order reserves its units). OrderService._units_already_ordered applies the same
rule. The advisory lock from d4a7c9e2f1b5 is kept.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e8b4d6f0a2c5'
down_revision: Union[str, Sequence[str], None] = 'c5e9a3b7d1f6'
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
            WHERE o.user_id = buyer_id AND oi.product_id = NEW.product_id
              AND o.status != 'cancelled';

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
