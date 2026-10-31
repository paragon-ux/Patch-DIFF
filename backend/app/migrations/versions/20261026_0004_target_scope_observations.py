"""create target_scope_observations table for server-issued Waymark observations

Adds `target_scope_observations` to persist server-issued structural scope
observations (`observation_id`) bound to a canonical target snapshot
(`target_file_id`, `editing_cycle_id`, `target_version`, `target_current_hash`),
pinned `waymark_engine_version`, resolved symbol identity (`symbol_name`,
`symbol_kind`, `symbol_parent`), 1-based line / UTF-16 column coordinates,
canonical Unicode code-point offsets (`scope_start`, `scope_end`),
`observed_scope_hash`, and optional `accepted_pdcp_log_id`.

Retention and lifecycle semantics:
- Observations are append-only server-issued records.
- An observation is valid for edit admission only while the locked target row
  remains at `target_version` and `target_current_hash` and has not yet been
  consumed by an accepted edit (`accepted_pdcp_log_id IS NULL`).
- Historical rows are retained alongside `append_only_pdcp_logs` so accepted
  scoped transactions can be audited and deterministically replayed across
  editing cycles.
- Downgrade refuses while any recorded scope observations exist; recorded
  observations are never discarded to make a downgrade succeed.

Revision ID: 20261026_0004
Revises: 20261022_0003
Create Date: 2026-10-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261026_0004"
down_revision: Union[str, None] = "20261022_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "target_scope_observations",
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("editing_cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_version", sa.BigInteger(), nullable=False),
        sa.Column("target_current_hash", sa.String(length=64), nullable=False),
        sa.Column("waymark_engine_version", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("symbol_name", sa.Text(), nullable=False),
        sa.Column("symbol_kind", sa.Text(), nullable=False),
        sa.Column("symbol_parent", sa.Text(), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("start_column", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("end_column", sa.Integer(), nullable=False),
        sa.Column("scope_start", sa.BigInteger(), nullable=False),
        sa.Column("scope_end", sa.BigInteger(), nullable=False),
        sa.Column("observed_scope_hash", sa.String(length=64), nullable=False),
        sa.Column("accepted_pdcp_log_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "target_version >= 0",
            name="ck_target_scope_observations_target_version",
        ),
        sa.CheckConstraint(
            "start_line >= 1 AND end_line >= start_line",
            name="ck_target_scope_observations_line_range",
        ),
        sa.CheckConstraint(
            "start_column >= 0 AND end_column >= 0",
            name="ck_target_scope_observations_columns",
        ),
        sa.CheckConstraint(
            "scope_start >= 0 AND scope_end >= scope_start",
            name="ck_target_scope_observations_scope_offsets",
        ),
        sa.ForeignKeyConstraint(
            ["target_file_id"],
            ["cloud_target_files.target_file_id"],
        ),
        sa.ForeignKeyConstraint(
            ["editing_cycle_id"],
            ["editing_cycles.editing_cycle_id"],
        ),
        sa.ForeignKeyConstraint(
            ["accepted_pdcp_log_id"],
            ["append_only_pdcp_logs.pdcp_log_id"],
        ),
        sa.PrimaryKeyConstraint("observation_id"),
        sa.UniqueConstraint(
            "accepted_pdcp_log_id",
            name="uq_target_scope_observations_accepted_log",
        ),
    )
    op.create_index(
        "ix_target_scope_observations_target_version",
        "target_scope_observations",
        ["target_file_id", "target_version"],
    )
    op.create_index(
        "ix_target_scope_observations_target_cycle",
        "target_scope_observations",
        ["target_file_id", "editing_cycle_id"],
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM target_scope_observations) THEN
                RAISE EXCEPTION 'Cannot downgrade 20261026_0004: recorded scope observations exist';
            END IF;
        END $$;
        """
    )
    op.drop_index(
        "ix_target_scope_observations_target_cycle",
        table_name="target_scope_observations",
    )
    op.drop_index(
        "ix_target_scope_observations_target_version",
        table_name="target_scope_observations",
    )
    op.drop_table("target_scope_observations")
