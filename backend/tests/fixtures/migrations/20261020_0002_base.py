"""typed transaction ledger and request deduplication support

Adds `origin` and `derived_json` to `append_only_manifest_ledger`, relaxes the
NOT NULL constraint on the five legacy manifest columns (`input_state`,
`output_state`, `affected_region`, `user_visible_change`, `risk`), and adds
`client_request_id`, `request_fingerprint`, and the partial unique index
`uq_pdcp_logs_target_client_request_id` on `append_only_pdcp_logs` so callers can
safely deduplicate transport retries and recover terminal outcomes after a lost
response.

Existing rows are unchanged (`origin = 'pdcp_manifest'`, `client_request_id = NULL`).
No history is deleted or rewritten.

Revision ID: 20261020_0002
Revises: 20260510_0001
Create Date: 2026-10-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261020_0002"
down_revision: Union[str, None] = "20260510_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RELAXED_COLUMNS = ("input_state", "output_state", "affected_region", "user_visible_change", "risk")


def upgrade() -> None:
    op.add_column(
        "append_only_manifest_ledger",
        sa.Column("origin", sa.Text(), server_default=sa.text("'pdcp_manifest'"), nullable=False),
    )
    op.add_column(
        "append_only_manifest_ledger",
        sa.Column("derived_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    for column in _RELAXED_COLUMNS:
        op.alter_column("append_only_manifest_ledger", column, existing_type=sa.Text(), nullable=True)

    op.add_column(
        "append_only_pdcp_logs",
        sa.Column("client_request_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "append_only_pdcp_logs",
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "uq_pdcp_logs_target_client_request_id",
        "append_only_pdcp_logs",
        ["target_file_id", "client_request_id"],
        unique=True,
        postgresql_where=sa.text("client_request_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Restoring NOT NULL is only possible when no typed rows exist. History is never
    # deleted to make a downgrade succeed.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM append_only_manifest_ledger WHERE origin <> 'pdcp_manifest') THEN
                RAISE EXCEPTION 'Cannot downgrade 20261020_0002: typed ledger rows exist';
            END IF;
        END $$;
        """
    )
    op.drop_index("uq_pdcp_logs_target_client_request_id", table_name="append_only_pdcp_logs")
    op.drop_column("append_only_pdcp_logs", "request_fingerprint")
    op.drop_column("append_only_pdcp_logs", "client_request_id")

    for column in reversed(_RELAXED_COLUMNS):
        op.alter_column("append_only_manifest_ledger", column, existing_type=sa.Text(), nullable=False)
    op.drop_column("append_only_manifest_ledger", "derived_json")
    op.drop_column("append_only_manifest_ledger", "origin")
