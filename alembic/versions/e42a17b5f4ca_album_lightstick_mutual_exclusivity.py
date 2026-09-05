"""album/lightstick details mutual exclusivity trigger

Revision ID: e42a17b5f4ca
Revises: a9e33e281ffe
Create Date: 2026-09-04 15:03:15.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e42a17b5f4ca'
down_revision: Union[str, Sequence[str], None] = 'a9e33e281ffe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# A product can be an album_details row OR a lightstick_details row, never
# both. Each table's PK is products.id, so nothing stops both existing for
# the same product_id without this — spans two separate tables, so it's a
# trigger pair rather than a single-row CHECK. A deliberate, explicitly-
# flagged exception to this design's usual "triggers are for money/fairness
# invariants, not general cross-table validation" rule (database-design.md
# §4/§6) — asked for directly, and a product that's simultaneously both
# kinds is a genuinely nonsensical state, not just an unusual one.


def upgrade() -> None:
    op.execute(sa.text(
        """
        CREATE OR REPLACE FUNCTION fn_enforce_single_product_detail_kind() RETURNS TRIGGER AS $$
        BEGIN
            IF TG_TABLE_NAME = 'album_details' THEN
                IF EXISTS (SELECT 1 FROM lightstick_details WHERE product_id = NEW.product_id) THEN
                    RAISE EXCEPTION 'product_id=% already has a lightstick_details row — a product cannot be both an album/single/EP and a lightstick',
                        NEW.product_id;
                END IF;
            ELSIF TG_TABLE_NAME = 'lightstick_details' THEN
                IF EXISTS (SELECT 1 FROM album_details WHERE product_id = NEW.product_id) THEN
                    RAISE EXCEPTION 'product_id=% already has an album_details row — a product cannot be both a lightstick and an album/single/EP',
                        NEW.product_id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    ))
    op.execute(sa.text(
        """
        CREATE TRIGGER trg_album_details_exclusive_kind
            BEFORE INSERT ON album_details
            FOR EACH ROW EXECUTE FUNCTION fn_enforce_single_product_detail_kind();
        """
    ))
    op.execute(sa.text(
        """
        CREATE TRIGGER trg_lightstick_details_exclusive_kind
            BEFORE INSERT ON lightstick_details
            FOR EACH ROW EXECUTE FUNCTION fn_enforce_single_product_detail_kind();
        """
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_lightstick_details_exclusive_kind ON lightstick_details"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_album_details_exclusive_kind ON album_details"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_enforce_single_product_detail_kind()"))
