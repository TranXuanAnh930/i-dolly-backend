"""merge lightstick category into merch

Revision ID: b60aec9ffc02
Revises: df79d71c6a2c
Create Date: 2026-09-06 11:16:40.736511

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b60aec9ffc02'
down_revision: Union[str, Sequence[str], None] = 'df79d71c6a2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Nothing in this project's actual business rules ever distinguished a
# lightstick from any other piece of official branded merch (the resale cap
# applies identically, company-ownership resolution is about to become
# identical, and even the strict-XOR "one clear owner" rule lightstick_details
# had is just as true of a tour hoodie) — see the design discussion this
# migration closes out. "Lightstick" was the one non-music category with its
# own top-level slot for no functional reason; merging it into "Merch" makes
# Album/Single/EP/Merch a more internally consistent 4-way split than the
# previous 5-way one. `lightstick_details` becomes the generic `merch_details`
# table going forward — nothing about its shape needed to change, only its
# name and the trigger function that hardcoded it.
#
# Cannot edit a9e33e281ffe (create_lightstick_details_table) or e42a17b5f4ca
# (album_lightstick_mutual_exclusivity) in place — unlike the earlier UUID PK
# rewrite, both have already run against a real Postgres instance this
# project's local dev stack. This is a forward migration on top of them.


def upgrade() -> None:
    # 1. Backfill BEFORE touching the category row or the table — reassign
    #    every product currently under "Lightstick" to "Merch".
    op.execute(sa.text("""
        UPDATE products
        SET category_id = (SELECT id FROM categories WHERE name = 'Merch')
        WHERE category_id = (SELECT id FROM categories WHERE name = 'Lightstick')
    """))

    # 2. Now safe to delete the category row — nothing references it.
    op.execute(sa.text("DELETE FROM categories WHERE name = 'Lightstick'"))

    # 3. Rename the table. Postgres does NOT rename constraints/indexes when
    #    a table is renamed — those need their own explicit renames (4-5).
    op.rename_table("lightstick_details", "merch_details")

    # 4. Rename the ownership CHECK constraint.
    op.execute(sa.text(
        "ALTER TABLE merch_details RENAME CONSTRAINT chk_lightstick_details_owner TO chk_merch_details_owner"
    ))

    # 5. Rename the 3 indexes.
    op.execute(sa.text("ALTER INDEX ix_lightstick_details_idol_id RENAME TO ix_merch_details_idol_id"))
    op.execute(sa.text("ALTER INDEX ix_lightstick_details_group_id RENAME TO ix_merch_details_group_id"))
    op.execute(sa.text("ALTER INDEX ix_lightstick_details_color_id RENAME TO ix_merch_details_color_id"))

    # 6. fn_enforce_single_product_detail_kind()'s body hardcodes
    #    "lightstick_details" as a literal table name in its SQL — renaming
    #    the table does NOT rewrite that string. Left unchanged, the next
    #    INSERT on either table would fail with
    #    `relation "lightstick_details" does not exist`, not the intended
    #    business-rule check. CREATE OR REPLACE with the corrected body —
    #    same trigger pair, same logic, new table name, new message text.
    #    IMPORTANT: app/exception/db_triggers.py's _MESSAGE_PATTERNS must be
    #    updated to match this new text ("already has a merch_details row")
    #    or trigger-error translation silently stops matching this trigger.
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION fn_enforce_single_product_detail_kind() RETURNS TRIGGER AS $$
        BEGIN
            IF TG_TABLE_NAME = 'album_details' THEN
                IF EXISTS (SELECT 1 FROM merch_details WHERE product_id = NEW.product_id) THEN
                    RAISE EXCEPTION 'product_id=% already has a merch_details row — a product cannot be both an album/single/EP and merch',
                        NEW.product_id;
                END IF;
            ELSIF TG_TABLE_NAME = 'merch_details' THEN
                IF EXISTS (SELECT 1 FROM album_details WHERE product_id = NEW.product_id) THEN
                    RAISE EXCEPTION 'product_id=% already has an album_details row — a product cannot be both merch and an album/single/EP',
                        NEW.product_id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """))

    # 7. Rename the trigger itself for consistency. Triggers follow a table
    #    through a rename automatically (they're bound to the table's OID,
    #    not its name) — this step is purely cosmetic, so `\d merch_details`
    #    doesn't show a trigger with "lightstick" still in its name.
    op.execute(sa.text(
        "ALTER TRIGGER trg_lightstick_details_exclusive_kind ON merch_details RENAME TO trg_merch_details_exclusive_kind"
    ))


def downgrade() -> None:
    # Steps 7 down to 3 reverse cleanly. Steps 1-2 (the category
    # backfill/delete) do NOT: nothing tracks which specific products were
    # reassigned from Lightstick to Merch, so there is no way to know which
    # merch_details rows to hand back to a recreated "Lightstick" category.
    # This downgrade restores the SCHEMA shape only — it recreates the
    # category row but leaves every product on "Merch", disclosed here
    # rather than silently pretending this is a full reversal.
    op.execute(sa.text(
        "ALTER TRIGGER trg_merch_details_exclusive_kind ON merch_details RENAME TO trg_lightstick_details_exclusive_kind"
    ))
    op.execute(sa.text("""
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
    """))
    op.execute(sa.text("ALTER INDEX ix_merch_details_color_id RENAME TO ix_lightstick_details_color_id"))
    op.execute(sa.text("ALTER INDEX ix_merch_details_group_id RENAME TO ix_lightstick_details_group_id"))
    op.execute(sa.text("ALTER INDEX ix_merch_details_idol_id RENAME TO ix_lightstick_details_idol_id"))
    op.execute(sa.text(
        "ALTER TABLE merch_details RENAME CONSTRAINT chk_merch_details_owner TO chk_lightstick_details_owner"
    ))
    op.rename_table("merch_details", "lightstick_details")
    op.execute(sa.text("""
        INSERT INTO categories (id, name, is_resale_capped)
        VALUES (gen_random_uuid(), 'Lightstick', true)
        ON CONFLICT (name) DO NOTHING
    """))
