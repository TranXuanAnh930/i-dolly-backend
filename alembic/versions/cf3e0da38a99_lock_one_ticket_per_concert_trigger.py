"""serialize fn_enforce_one_ticket_per_concert per (user, concert)

Revision ID: cf3e0da38a99
Revises: a9d3f5b7c1e2
Create Date: 2026-09-26 00:00:00.000000

The trigger counted the user's live tickets for the concert and then let the insert through. Under
READ COMMITTED two concurrent inserts for the same user and concert (e.g. two different tiers)
can't see each other's uncommitted row, so both passed. A transaction-scoped advisory lock on
(user, concert), taken before the count, makes the second insert wait for the first to commit;
the count then sees the committed ticket and raises.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'cf3e0da38a99'
down_revision: Union[str, Sequence[str], None] = 'a9d3f5b7c1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text(
        """
        CREATE OR REPLACE FUNCTION fn_enforce_one_ticket_per_concert() RETURNS TRIGGER AS $$
        DECLARE
            target_concert_id UUID;
            existing_live_tickets INTEGER;
        BEGIN
            SELECT c.id INTO target_concert_id
            FROM ticket_types tt JOIN concerts c ON c.id = tt.concert_id
            WHERE tt.id = NEW.ticket_type_id;

            -- Held until commit; a hash collision only serializes unrelated inserts.
            PERFORM pg_advisory_xact_lock(
                hashtextextended(NEW.user_id::text || ':' || target_concert_id::text, 0)
            );

            SELECT COUNT(*) INTO existing_live_tickets
            FROM tickets t JOIN ticket_types tt ON tt.id = t.ticket_type_id
            WHERE t.user_id = NEW.user_id
              AND tt.concert_id = target_concert_id
              AND t.status IN ('reserved', 'pending_payment', 'paid', 'used');

            IF existing_live_tickets > 0 THEN
                RAISE EXCEPTION 'user_id=% already holds a live ticket for concert_id=% — only one ticket per person per concert (lottery or direct) is allowed',
                    NEW.user_id, target_concert_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    ))


def downgrade() -> None:
    op.execute(sa.text(
        """
        CREATE OR REPLACE FUNCTION fn_enforce_one_ticket_per_concert() RETURNS TRIGGER AS $$
        DECLARE
            target_concert_id UUID;
            existing_live_tickets INTEGER;
        BEGIN
            SELECT c.id INTO target_concert_id
            FROM ticket_types tt JOIN concerts c ON c.id = tt.concert_id
            WHERE tt.id = NEW.ticket_type_id;

            SELECT COUNT(*) INTO existing_live_tickets
            FROM tickets t JOIN ticket_types tt ON tt.id = t.ticket_type_id
            WHERE t.user_id = NEW.user_id
              AND tt.concert_id = target_concert_id
              AND t.status IN ('reserved', 'pending_payment', 'paid', 'used');

            IF existing_live_tickets > 0 THEN
                RAISE EXCEPTION 'user_id=% already holds a live ticket for concert_id=% — only one ticket per person per concert (lottery or direct) is allowed',
                    NEW.user_id, target_concert_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    ))
