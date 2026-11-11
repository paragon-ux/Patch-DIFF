"""Persist active workspace targets and explicit recovery outcomes.

Revision ID: 20261111_0007
Revises: 20261105_0006
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261111_0007"
down_revision = "20261105_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_bindings",
        sa.Column("binding_id", sa.Uuid(), primary_key=True),
        sa.Column("root_identity", sa.Text(), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("path_sha256", sa.String(64), nullable=False),
        sa.Column("physical_destination", sa.Text(), unique=True),
        sa.Column("active_target_file_id", sa.Uuid(), sa.ForeignKey("cloud_target_files.target_file_id")),
        sa.UniqueConstraint("root_identity", "path_sha256", name="uq_workspace_bindings_root_path"),
    )
    op.create_table(
        "workspace_binding_members",
        sa.Column("target_file_id", sa.Uuid(), sa.ForeignKey("cloud_target_files.target_file_id"), primary_key=True),
        sa.Column("binding_id", sa.Uuid(), sa.ForeignKey("workspace_bindings.binding_id"), nullable=False),
        sa.Column("superseded_by_target_file_id", sa.Uuid()),
        sa.UniqueConstraint("binding_id", "target_file_id", name="uq_workspace_binding_members_binding_target"),
        sa.CheckConstraint("superseded_by_target_file_id <> target_file_id", name="ck_workspace_binding_members_successor"),
        sa.ForeignKeyConstraint(
            ["binding_id", "superseded_by_target_file_id"],
            ["workspace_binding_members.binding_id", "workspace_binding_members.target_file_id"],
            name="fk_workspace_binding_members_successor", deferrable=True, initially="DEFERRED",
        ),
    )
    op.create_foreign_key(
        "fk_workspace_bindings_active_member", "workspace_bindings", "workspace_binding_members",
        ["binding_id", "active_target_file_id"], ["binding_id", "target_file_id"],
        deferrable=True, initially="DEFERRED",
    )
    op.create_table(
        "workspace_recovery_receipts",
        sa.Column("binding_id", sa.Uuid(), sa.ForeignKey("workspace_bindings.binding_id"), primary_key=True),
        sa.Column("client_request_id", sa.String(128), primary_key=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("outcome", postgresql.JSONB(), nullable=False),
    )
    # Record only the logical identity available in the old schema. The server
    # claims the physical destination when it can open the pinned directories.
    op.execute("""
        CREATE TEMPORARY TABLE workspace_legacy_members ON COMMIT DROP AS
        SELECT target_file_id,
               source_line_endings->>'workspace_root_identity' AS root_identity,
               replace(filename, chr(92), '/') AS relative_path
        FROM cloud_target_files
        WHERE source_line_endings->'workspace_tracked' = 'true'::jsonb
          AND jsonb_typeof(source_line_endings->'workspace_root_identity') = 'string'
          AND source_line_endings->>'workspace_root_identity' ~ '^[0-9]{1,20}:[0-9]{1,20}$'
          AND filename <> ''
    """)
    op.execute("""
        INSERT INTO workspace_bindings (binding_id, root_identity, relative_path, path_sha256, active_target_file_id)
        SELECT gen_random_uuid(), root_identity, relative_path,
               encode(sha256(convert_to(relative_path, 'UTF8')), 'hex'),
               CASE WHEN count(*) = 1 THEN min(target_file_id::text)::uuid END
        FROM workspace_legacy_members
        GROUP BY root_identity, relative_path
    """)
    op.execute("""
        INSERT INTO workspace_binding_members (target_file_id, binding_id)
        SELECT legacy.target_file_id, binding.binding_id
        FROM workspace_legacy_members AS legacy
        JOIN workspace_bindings AS binding USING (root_identity, relative_path)
    """)


def downgrade() -> None:
    op.execute("LOCK TABLE workspace_bindings, workspace_binding_members, workspace_recovery_receipts IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM workspace_bindings) THEN
                RAISE EXCEPTION 'Cannot downgrade 20261111_0007: workspace binding evidence exists';
            END IF;
        END $$;
    """)
    op.drop_table("workspace_recovery_receipts")
    op.drop_constraint("fk_workspace_bindings_active_member", "workspace_bindings", type_="foreignkey")
    op.drop_table("workspace_binding_members")
    op.drop_table("workspace_bindings")
