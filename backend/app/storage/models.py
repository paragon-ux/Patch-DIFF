from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Users(TimestampMixin, Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_subject: Mapped[str | None] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Projects(TimestampMixin, Base):
    __tablename__ = "projects"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProjectMemberships(TimestampMixin, Base):
    __tablename__ = "project_memberships"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_project_memberships_role"),
        UniqueConstraint("project_id", "user_id", name="uq_project_memberships_project_user"),
    )

    project_membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.project_id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)


class CloudTargetFiles(TimestampMixin, Base):
    __tablename__ = "cloud_target_files"
    __table_args__ = (
        Index("ix_cloud_target_files_project_id", "project_id"),
        Index("ix_cloud_target_files_active_editing_cycle_id", "active_editing_cycle_id"),
        Index("ix_cloud_target_files_current_hash", "current_hash"),
    )

    target_file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.project_id"), nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    current_content: Mapped[str] = mapped_column(Text, nullable=False)
    current_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Raw upload line-ending facts recorded before LF canonicalization (0003); NULL = unknown.
    source_line_endings: Mapped[dict | None] = mapped_column(JSONB)
    active_editing_cycle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "editing_cycles.editing_cycle_id",
            use_alter=True,
            name="fk_cloud_target_files_active_cycle",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=False,
    )
    latest_accepted_pdcp_log_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("append_only_pdcp_logs.pdcp_log_id", use_alter=True, name="fk_cloud_target_files_latest_log")
    )
    initial_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("target_snapshots.snapshot_id", use_alter=True, name="fk_cloud_target_files_initial_snapshot")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class EditingCycles(TimestampMixin, Base):
    __tablename__ = "editing_cycles"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'closed')", name="ck_editing_cycles_status"),
        UniqueConstraint("target_file_id", "cycle_index", name="uq_editing_cycles_target_cycle_index"),
        Index(
            "uq_editing_cycles_one_active_per_target",
            "target_file_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    editing_cycle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cloud_target_files.target_file_id"), nullable=False)
    cycle_index: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))
    closed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))
    save_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("target_snapshots.snapshot_id", use_alter=True, name="fk_editing_cycles_save_snapshot")
    )


class TargetSnapshots(TimestampMixin, Base):
    __tablename__ = "target_snapshots"
    __table_args__ = (
        CheckConstraint("snapshot_reason IN ('initial_upload', 'save_checkpoint')", name="ck_target_snapshots_reason"),
        Index("ix_target_snapshots_target_created_at", "target_file_id", "created_at"),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cloud_target_files.target_file_id"), nullable=False)
    editing_cycle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("editing_cycles.editing_cycle_id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot_reason: Mapped[str] = mapped_column(Text, nullable=False)
    base_pdcp_log_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("append_only_pdcp_logs.pdcp_log_id", use_alter=True, name="fk_target_snapshots_base_log")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))


class AppendOnlyPdcpLogs(TimestampMixin, Base):
    __tablename__ = "append_only_pdcp_logs"
    __table_args__ = (
        CheckConstraint("status IN ('accepted', 'rejected')", name="ck_append_only_pdcp_logs_status"),
        Index("ix_append_only_pdcp_logs_target_sequence", "target_file_id", "log_sequence"),
        Index("ix_append_only_pdcp_logs_target_created_at", "target_file_id", "created_at"),
        Index("ix_append_only_pdcp_logs_parent", "parent_pdcp_log_id"),
        Index("ix_append_only_pdcp_logs_status_failure", "status", "failure_reason"),
        Index(
            "uq_pdcp_logs_target_client_request_id",
            "target_file_id",
            "client_request_id",
            unique=True,
            postgresql_where=text("client_request_id IS NOT NULL"),
        ),
    )

    pdcp_log_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    log_sequence: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    target_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cloud_target_files.target_file_id"), nullable=False)
    editing_cycle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("editing_cycles.editing_cycle_id"), nullable=False)
    parent_pdcp_log_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("append_only_pdcp_logs.pdcp_log_id"))
    regeneration_attempt: Mapped[int | None] = mapped_column(Integer)
    regeneration_source: Mapped[str | None] = mapped_column(Text)
    submission_source: Mapped[str] = mapped_column(Text, nullable=False)
    protocol_version: Mapped[str] = mapped_column(Text, nullable=False)
    runtime_version: Mapped[str] = mapped_column(Text, nullable=False)
    pdcp_content: Mapped[str] = mapped_column(Text, nullable=False)
    pdcp_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    failure_detail: Mapped[str | None] = mapped_column(Text)
    failed_change_id: Mapped[str | None] = mapped_column(Text)
    diagnostic_json: Mapped[dict | None] = mapped_column(JSONB)
    expected_target_version: Mapped[int | None] = mapped_column(BigInteger)
    expected_current_hash: Mapped[str | None] = mapped_column(String(64))
    before_version: Mapped[int | None] = mapped_column(BigInteger)
    after_version: Mapped[int | None] = mapped_column(BigInteger)
    before_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    after_hash: Mapped[str | None] = mapped_column(String(64))
    change_count: Mapped[int] = mapped_column(Integer, nullable=False)
    client_request_id: Mapped[str | None] = mapped_column(Text)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))


class AppendOnlyManifestLedger(TimestampMixin, Base):
    __tablename__ = "append_only_manifest_ledger"
    __table_args__ = (
        CheckConstraint("risk IN ('low', 'medium', 'high')", name="ck_append_only_manifest_ledger_risk"),
        UniqueConstraint("pdcp_log_id", "change_index", name="uq_manifest_ledger_log_change_index"),
        UniqueConstraint("pdcp_log_id", "change_id", name="uq_manifest_ledger_log_change_id"),
        Index(
            "ix_manifest_ledger_target_cycle_sequence",
            "target_file_id",
            "editing_cycle_id",
            "ledger_sequence",
        ),
    )

    manifest_entry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ledger_sequence: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    target_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cloud_target_files.target_file_id"), nullable=False)
    editing_cycle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("editing_cycles.editing_cycle_id"), nullable=False)
    pdcp_log_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("append_only_pdcp_logs.pdcp_log_id"), nullable=False)
    change_index: Mapped[int] = mapped_column(Integer, nullable=False)
    change_id: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(Text, nullable=False)
    # NULL for typed (patchdiff-tx/1) rows: those four fields are not collected there.
    input_state: Mapped[str | None] = mapped_column(Text)
    output_state: Mapped[str | None] = mapped_column(Text)
    affected_region: Mapped[str | None] = mapped_column(Text)
    user_visible_change: Mapped[str | None] = mapped_column(Text)
    risk: Mapped[str | None] = mapped_column(Text)
    # 'pdcp_manifest' = model-asserted manifest fields; 'typed' = advisory intent plus
    # runtime-derived facts in derived_json.
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pdcp_manifest'"))
    derived_json: Mapped[dict | None] = mapped_column(JSONB)


class CurrentPdcpFiles(TimestampMixin, Base):
    __tablename__ = "current_pdcp_files"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_validation', 'accepted', 'rejected', 'superseded')",
            name="ck_current_pdcp_files_status",
        ),
        UniqueConstraint("target_file_id", name="uq_current_pdcp_files_target"),
    )

    pdcp_file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cloud_target_files.target_file_id"), nullable=False)
    editing_cycle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("editing_cycles.editing_cycle_id"), nullable=False)
    protocol_version: Mapped[str] = mapped_column(Text, nullable=False)
    pdcp_content: Mapped[str] = mapped_column(Text, nullable=False)
    pdcp_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    submission_source: Mapped[str] = mapped_column(Text, nullable=False)
    parent_pdcp_log_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("append_only_pdcp_logs.pdcp_log_id"))
    regeneration_attempt: Mapped[int | None] = mapped_column(Integer)
    regeneration_source: Mapped[str | None] = mapped_column(Text)
    last_pdcp_log_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("append_only_pdcp_logs.pdcp_log_id"))
    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.user_id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

class TargetScopeObservations(TimestampMixin, Base):
    __tablename__ = "target_scope_observations"
    __table_args__ = (
        CheckConstraint("target_version >= 0", name="ck_target_scope_observations_target_version"),
        CheckConstraint(
            "start_line >= 1 AND end_line >= start_line",
            name="ck_target_scope_observations_line_range",
        ),
        CheckConstraint(
            "start_column >= 0 AND end_column >= 0",
            name="ck_target_scope_observations_columns",
        ),
        CheckConstraint(
            "scope_start >= 0 AND scope_end >= scope_start",
            name="ck_target_scope_observations_scope_offsets",
        ),
        UniqueConstraint("accepted_pdcp_log_id", name="uq_target_scope_observations_accepted_log"),
        Index("ix_target_scope_observations_target_version", "target_file_id", "target_version"),
        Index("ix_target_scope_observations_target_cycle", "target_file_id", "editing_cycle_id"),
    )

    observation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cloud_target_files.target_file_id"), nullable=False)
    editing_cycle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("editing_cycles.editing_cycle_id"), nullable=False)
    target_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_current_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    waymark_engine_version: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False)
    symbol_name: Mapped[str] = mapped_column(Text, nullable=False)
    symbol_kind: Mapped[str] = mapped_column(Text, nullable=False)
    symbol_parent: Mapped[str | None] = mapped_column(Text)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    start_column: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_column: Mapped[int] = mapped_column(Integer, nullable=False)
    scope_start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scope_end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    observed_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_pdcp_log_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("append_only_pdcp_logs.pdcp_log_id")
    )
