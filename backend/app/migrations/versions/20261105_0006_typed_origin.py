"""Adopt typed-only ledger origins without rewriting existing audit history.

Revision ID: 20261105_0006
Revises: 20261027_0005
Create Date: 2026-11-05
"""

from alembic import op
import sqlalchemy as sa

revision = "20261105_0006"
down_revision = "20261027_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the compatibility check and DDL over one stable ledger state.
    op.execute("LOCK TABLE append_only_manifest_ledger IN ACCESS EXCLUSIVE MODE")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM append_only_manifest_ledger WHERE origin <> 'typed') THEN
                RAISE EXCEPTION 'Cannot upgrade 20261105_0006: non-typed ledger origins exist; audit history was not changed';
            END IF;
        END $$;
        """
    )
    op.alter_column("append_only_manifest_ledger", "origin", existing_type=sa.Text(),
                    server_default=sa.text("'typed'"), existing_nullable=False)
    # The unreleased candidate also installed this constraint under revision 0002.
    op.execute("ALTER TABLE append_only_manifest_ledger DROP CONSTRAINT IF EXISTS ck_append_only_manifest_ledger_origin")
    op.create_check_constraint("ck_append_only_manifest_ledger_origin", "append_only_manifest_ledger", "origin = 'typed'")


def downgrade() -> None:
    op.drop_constraint("ck_append_only_manifest_ledger_origin", "append_only_manifest_ledger", type_="check")
    op.alter_column("append_only_manifest_ledger", "origin", existing_type=sa.Text(),
                    server_default=sa.text("'pdcp_manifest'"), existing_nullable=False)
