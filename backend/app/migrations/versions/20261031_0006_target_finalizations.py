"""Add target_finalizations table for durable finalization idempotency.

Revision ID: 20261031_0006
Revises: 20261027_0005
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261031_0006"
down_revision = "20261027_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "target_finalizations",
        sa.Column("finalization_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("target_file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cloud_target_files.target_file_id"), nullable=False),
        sa.Column("client_request_id", sa.String(128), nullable=False),
        sa.Column("fingerprint_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("target_snapshots.snapshot_id"), nullable=True),
        sa.Column("closed_editing_cycle_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("editing_cycles.editing_cycle_id"), nullable=True),
        sa.Column("new_editing_cycle_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("editing_cycles.editing_cycle_id"), nullable=True),
        sa.Column("saved_target_version", sa.BigInteger(), nullable=True),
        sa.Column("canonical_current_hash", sa.String(64), nullable=True),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("export_format", sa.Text(), nullable=True),
        sa.Column("content_eol", sa.Text(), nullable=True),
        sa.Column("source_line_endings", postgresql.JSONB(), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("content_bytes", sa.BigInteger(), nullable=True),
        sa.Column("exported_content", sa.Text(), nullable=True),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("target_file_id", "client_request_id", name="uq_target_finalizations_target_key"),
        sa.CheckConstraint(
            "(status = 'completed' AND snapshot_id IS NOT NULL AND closed_editing_cycle_id IS NOT NULL AND new_editing_cycle_id IS NOT NULL AND saved_target_version IS NOT NULL AND canonical_current_hash IS NOT NULL AND content_sha256 IS NOT NULL) OR "
            "(status != 'completed' AND failure_detail IS NOT NULL)",
            name="ck_target_finalizations_status_fields",
        ),
    )
    op.create_index("ix_target_finalizations_target_key", "target_finalizations", ["target_file_id", "client_request_id"])
    op.create_index("ix_target_finalizations_target_created", "target_finalizations", ["target_file_id", "created_at"])


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM target_finalizations) THEN
            RAISE EXCEPTION 'Cannot downgrade 20261031_0006: target finalization records exist';
        END IF;
    END $$;""")
    op.drop_index("ix_target_finalizations_target_created", table_name="target_finalizations")
    op.drop_index("ix_target_finalizations_target_key", table_name="target_finalizations")
    op.drop_table("target_finalizations")
