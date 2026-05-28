"""initial PatchDIFF MVP schema

Revision ID: 20260510_0001
Revises:
Create Date: 2026-05-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260510_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_subject", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("external_subject"),
    )

    op.create_table(
        "projects",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("project_id"),
    )

    op.create_table(
        "project_memberships",
        sa.Column("project_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_project_memberships_role"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("project_membership_id"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_memberships_project_user"),
    )

    op.create_table(
        "cloud_target_files",
        sa.Column("target_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("current_content", sa.Text(), nullable=False),
        sa.Column("current_hash", sa.String(length=64), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("active_editing_cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("latest_accepted_pdcp_log_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("initial_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"]),
        sa.PrimaryKeyConstraint("target_file_id"),
    )
    op.create_index("ix_cloud_target_files_project_id", "cloud_target_files", ["project_id"])
    op.create_index("ix_cloud_target_files_active_editing_cycle_id", "cloud_target_files", ["active_editing_cycle_id"])
    op.create_index("ix_cloud_target_files_current_hash", "cloud_target_files", ["current_hash"])

    op.create_table(
        "editing_cycles",
        sa.Column("editing_cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cycle_index", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("closed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("save_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'closed')", name="ck_editing_cycles_status"),
        sa.ForeignKeyConstraint(["closed_by_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["opened_by_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["target_file_id"], ["cloud_target_files.target_file_id"]),
        sa.PrimaryKeyConstraint("editing_cycle_id"),
        sa.UniqueConstraint("target_file_id", "cycle_index", name="uq_editing_cycles_target_cycle_index"),
    )
    op.create_index(
        "uq_editing_cycles_one_active_per_target",
        "editing_cycles",
        ["target_file_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "target_snapshots",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("editing_cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("snapshot_reason", sa.Text(), nullable=False),
        sa.Column("base_pdcp_log_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "snapshot_reason IN ('initial_upload', 'save_checkpoint')",
            name="ck_target_snapshots_reason",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["editing_cycle_id"], ["editing_cycles.editing_cycle_id"]),
        sa.ForeignKeyConstraint(["target_file_id"], ["cloud_target_files.target_file_id"]),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    op.create_index("ix_target_snapshots_target_created_at", "target_snapshots", ["target_file_id", "created_at"])

    op.create_table(
        "append_only_pdcp_logs",
        sa.Column("pdcp_log_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("log_sequence", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("target_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("editing_cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_pdcp_log_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("regeneration_attempt", sa.Integer(), nullable=True),
        sa.Column("regeneration_source", sa.Text(), nullable=True),
        sa.Column("submission_source", sa.Text(), nullable=False),
        sa.Column("protocol_version", sa.Text(), nullable=False),
        sa.Column("runtime_version", sa.Text(), nullable=False),
        sa.Column("pdcp_content", sa.Text(), nullable=False),
        sa.Column("pdcp_content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("failed_change_id", sa.Text(), nullable=True),
        sa.Column("diagnostic_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expected_target_version", sa.BigInteger(), nullable=True),
        sa.Column("expected_current_hash", sa.String(length=64), nullable=True),
        sa.Column("before_version", sa.BigInteger(), nullable=True),
        sa.Column("after_version", sa.BigInteger(), nullable=True),
        sa.Column("before_hash", sa.String(length=64), nullable=False),
        sa.Column("after_hash", sa.String(length=64), nullable=True),
        sa.Column("change_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('accepted', 'rejected')", name="ck_append_only_pdcp_logs_status"),
        sa.ForeignKeyConstraint(["editing_cycle_id"], ["editing_cycles.editing_cycle_id"]),
        sa.ForeignKeyConstraint(["parent_pdcp_log_id"], ["append_only_pdcp_logs.pdcp_log_id"]),
        sa.ForeignKeyConstraint(["target_file_id"], ["cloud_target_files.target_file_id"]),
        sa.PrimaryKeyConstraint("pdcp_log_id"),
        sa.UniqueConstraint("log_sequence"),
    )
    op.create_index("ix_append_only_pdcp_logs_target_sequence", "append_only_pdcp_logs", ["target_file_id", "log_sequence"])
    op.create_index("ix_append_only_pdcp_logs_target_created_at", "append_only_pdcp_logs", ["target_file_id", "created_at"])
    op.create_index("ix_append_only_pdcp_logs_parent", "append_only_pdcp_logs", ["parent_pdcp_log_id"])
    op.create_index("ix_append_only_pdcp_logs_status_failure", "append_only_pdcp_logs", ["status", "failure_reason"])

    op.create_table(
        "append_only_manifest_ledger",
        sa.Column("manifest_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ledger_sequence", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("target_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("editing_cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pdcp_log_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("change_index", sa.Integer(), nullable=False),
        sa.Column("change_id", sa.Text(), nullable=False),
        sa.Column("intent", sa.Text(), nullable=False),
        sa.Column("input_state", sa.Text(), nullable=False),
        sa.Column("output_state", sa.Text(), nullable=False),
        sa.Column("affected_region", sa.Text(), nullable=False),
        sa.Column("user_visible_change", sa.Text(), nullable=False),
        sa.Column("risk", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("risk IN ('low', 'medium', 'high')", name="ck_append_only_manifest_ledger_risk"),
        sa.ForeignKeyConstraint(["editing_cycle_id"], ["editing_cycles.editing_cycle_id"]),
        sa.ForeignKeyConstraint(["pdcp_log_id"], ["append_only_pdcp_logs.pdcp_log_id"]),
        sa.ForeignKeyConstraint(["target_file_id"], ["cloud_target_files.target_file_id"]),
        sa.PrimaryKeyConstraint("manifest_entry_id"),
        sa.UniqueConstraint("ledger_sequence"),
        sa.UniqueConstraint("pdcp_log_id", "change_id", name="uq_manifest_ledger_log_change_id"),
        sa.UniqueConstraint("pdcp_log_id", "change_index", name="uq_manifest_ledger_log_change_index"),
    )
    op.create_index(
        "ix_manifest_ledger_target_cycle_sequence",
        "append_only_manifest_ledger",
        ["target_file_id", "editing_cycle_id", "ledger_sequence"],
    )

    op.create_table(
        "current_pdcp_files",
        sa.Column("pdcp_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("editing_cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("protocol_version", sa.Text(), nullable=False),
        sa.Column("pdcp_content", sa.Text(), nullable=False),
        sa.Column("pdcp_content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("submission_source", sa.Text(), nullable=False),
        sa.Column("parent_pdcp_log_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("regeneration_attempt", sa.Integer(), nullable=True),
        sa.Column("regeneration_source", sa.Text(), nullable=True),
        sa.Column("last_pdcp_log_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending_validation', 'accepted', 'rejected', 'superseded')",
            name="ck_current_pdcp_files_status",
        ),
        sa.ForeignKeyConstraint(["editing_cycle_id"], ["editing_cycles.editing_cycle_id"]),
        sa.ForeignKeyConstraint(["last_pdcp_log_id"], ["append_only_pdcp_logs.pdcp_log_id"]),
        sa.ForeignKeyConstraint(["parent_pdcp_log_id"], ["append_only_pdcp_logs.pdcp_log_id"]),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["target_file_id"], ["cloud_target_files.target_file_id"]),
        sa.PrimaryKeyConstraint("pdcp_file_id"),
        sa.UniqueConstraint("target_file_id", name="uq_current_pdcp_files_target"),
    )

    op.create_foreign_key(
        "fk_cloud_target_files_active_cycle",
        "cloud_target_files",
        "editing_cycles",
        ["active_editing_cycle_id"],
        ["editing_cycle_id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_cloud_target_files_initial_snapshot",
        "cloud_target_files",
        "target_snapshots",
        ["initial_snapshot_id"],
        ["snapshot_id"],
    )
    op.create_foreign_key(
        "fk_cloud_target_files_latest_log",
        "cloud_target_files",
        "append_only_pdcp_logs",
        ["latest_accepted_pdcp_log_id"],
        ["pdcp_log_id"],
    )
    op.create_foreign_key(
        "fk_editing_cycles_save_snapshot",
        "editing_cycles",
        "target_snapshots",
        ["save_snapshot_id"],
        ["snapshot_id"],
    )
    op.create_foreign_key(
        "fk_target_snapshots_base_log",
        "target_snapshots",
        "append_only_pdcp_logs",
        ["base_pdcp_log_id"],
        ["pdcp_log_id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_target_snapshots_base_log", "target_snapshots", type_="foreignkey")
    op.drop_constraint("fk_editing_cycles_save_snapshot", "editing_cycles", type_="foreignkey")
    op.drop_constraint("fk_cloud_target_files_latest_log", "cloud_target_files", type_="foreignkey")
    op.drop_constraint("fk_cloud_target_files_initial_snapshot", "cloud_target_files", type_="foreignkey")
    op.drop_constraint("fk_cloud_target_files_active_cycle", "cloud_target_files", type_="foreignkey")

    op.drop_table("current_pdcp_files")
    op.drop_index("ix_manifest_ledger_target_cycle_sequence", table_name="append_only_manifest_ledger")
    op.drop_table("append_only_manifest_ledger")
    op.drop_index("ix_append_only_pdcp_logs_status_failure", table_name="append_only_pdcp_logs")
    op.drop_index("ix_append_only_pdcp_logs_parent", table_name="append_only_pdcp_logs")
    op.drop_index("ix_append_only_pdcp_logs_target_created_at", table_name="append_only_pdcp_logs")
    op.drop_index("ix_append_only_pdcp_logs_target_sequence", table_name="append_only_pdcp_logs")
    op.drop_table("append_only_pdcp_logs")
    op.drop_index("ix_target_snapshots_target_created_at", table_name="target_snapshots")
    op.drop_table("target_snapshots")
    op.drop_index("uq_editing_cycles_one_active_per_target", table_name="editing_cycles")
    op.drop_table("editing_cycles")
    op.drop_index("ix_cloud_target_files_current_hash", table_name="cloud_target_files")
    op.drop_index("ix_cloud_target_files_active_editing_cycle_id", table_name="cloud_target_files")
    op.drop_index("ix_cloud_target_files_project_id", table_name="cloud_target_files")
    op.drop_table("cloud_target_files")
    op.drop_table("project_memberships")
    op.drop_table("projects")
    op.drop_table("users")
