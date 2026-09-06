"""rename leftover lightstick_details constraint names

Revision ID: 133d9b4f9d17
Revises: b60aec9ffc02
Create Date: 2026-09-06 12:13:35.371677

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '133d9b4f9d17'
down_revision: Union[str, Sequence[str], None] = 'b60aec9ffc02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# b60aec9ffc02 renamed the table plus every EXPLICITLY-named object on it
# (the chk_lightstick_details_owner CHECK constraint, the 3 ix_lightstick_
# details_* indexes) — but missed the objects Postgres names automatically
# when a migration doesn't give them a name: the primary key constraint and
# all 4 foreign key constraints. `ALTER TABLE ... RENAME TO` only renames
# the table itself; every constraint keeps whatever name it already had,
# named or auto-named alike. Found by querying the live local dev Postgres
# directly (pg_constraint/pg_indexes) after applying b60aec9ffc02, not by
# re-reading the migration source — the auto-generated names were never
# written down anywhere to grep for.
#
# Renaming a PK constraint via ALTER TABLE ... RENAME CONSTRAINT also
# renames its backing index automatically (the index IS the constraint's
# implementation for a PK) — no separate index rename needed for that one,
# unlike the 3 secondary indexes in b60aec9ffc02 which were separate objects
# from any constraint.


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE merch_details RENAME CONSTRAINT lightstick_details_pkey TO merch_details_pkey"
    ))
    op.execute(sa.text(
        "ALTER TABLE merch_details RENAME CONSTRAINT lightstick_details_product_id_fkey TO merch_details_product_id_fkey"
    ))
    op.execute(sa.text(
        "ALTER TABLE merch_details RENAME CONSTRAINT lightstick_details_idol_id_fkey TO merch_details_idol_id_fkey"
    ))
    op.execute(sa.text(
        "ALTER TABLE merch_details RENAME CONSTRAINT lightstick_details_group_id_fkey TO merch_details_group_id_fkey"
    ))
    op.execute(sa.text(
        "ALTER TABLE merch_details RENAME CONSTRAINT lightstick_details_color_id_fkey TO merch_details_color_id_fkey"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE merch_details RENAME CONSTRAINT merch_details_color_id_fkey TO lightstick_details_color_id_fkey"
    ))
    op.execute(sa.text(
        "ALTER TABLE merch_details RENAME CONSTRAINT merch_details_group_id_fkey TO lightstick_details_group_id_fkey"
    ))
    op.execute(sa.text(
        "ALTER TABLE merch_details RENAME CONSTRAINT merch_details_idol_id_fkey TO lightstick_details_idol_id_fkey"
    ))
    op.execute(sa.text(
        "ALTER TABLE merch_details RENAME CONSTRAINT merch_details_product_id_fkey TO lightstick_details_product_id_fkey"
    ))
    op.execute(sa.text(
        "ALTER TABLE merch_details RENAME CONSTRAINT merch_details_pkey TO lightstick_details_pkey"
    ))
