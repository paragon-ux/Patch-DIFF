"""Add cloud_target_files.history_revision, immutable audit triggers, role column grants, and target_finalization_export_chunks.

Revision ID: 20261101_0008
Revises: 20261031_0007
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261101_0008"
down_revision: Union[str, None] = "20261031_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cloud_target_files",
        sa.Column("history_revision", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )

    op.execute(
        """
        UPDATE cloud_target_files c
           SET history_revision = (
               SELECT count(*)
                 FROM append_only_pdcp_logs l
                WHERE l.target_file_id = c.target_file_id
                  AND l.status = 'accepted'
           ) + (
               SELECT count(*)
                 FROM target_scope_observations o
                WHERE o.target_file_id = c.target_file_id
                  AND o.accepted_pdcp_log_id IS NOT NULL
           );
        """
    )

    op.create_table(
        "target_finalization_export_chunks",
        sa.Column(
            "finalization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("target_finalizations.finalization_id"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("payload_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("byte_length", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "finalization_id",
            "chunk_index",
            name="pk_target_finalization_export_chunks",
        ),
        sa.CheckConstraint(
            "byte_length > 0 AND byte_length <= 262144",
            name="ck_target_finalization_export_chunks_byte_length",
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_target_finalization_export_chunks_chunk_index",
        ),
    )

    # 1. Immutability trigger function for append-only audit and chunk tables
    op.execute(
        """
        CREATE OR REPLACE FUNCTION patchdiff_enforce_immutable_audit_row()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'Immutable audit table %.%: % is prohibited for role %',
                TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP, current_user
                USING ERRCODE = '42501';
        END;
        $$;
        """
    )

    for tbl in (
        "append_only_pdcp_logs",
        "append_only_manifest_ledger",
        "target_snapshots",
        "target_finalization_export_chunks",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_immutable_{tbl} ON {tbl};")
        op.execute(
            f"""
            CREATE TRIGGER trg_immutable_{tbl}
            BEFORE UPDATE OR DELETE ON {tbl}
            FOR EACH ROW
            EXECUTE FUNCTION patchdiff_enforce_immutable_audit_row();
            """
        )

    # 2. One-way observation linkage validation & immutability trigger on target_scope_observations
    op.execute(
        """
        CREATE OR REPLACE FUNCTION patchdiff_enforce_scope_observation_immutability()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            valid_log boolean;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.accepted_pdcp_log_id IS NOT NULL THEN
                    RAISE EXCEPTION 'Observation must be inserted unconsumed before its one-way accepted log linkage'
                        USING ERRCODE = '42501';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Immutable audit table %.target_scope_observations: DELETE is prohibited for role %',
                    TG_TABLE_SCHEMA, current_user
                    USING ERRCODE = '42501';
            END IF;
            IF OLD.accepted_pdcp_log_id IS NOT NULL OR NEW.accepted_pdcp_log_id IS NULL THEN
                RAISE EXCEPTION 'Immutable audit table %.target_scope_observations: only one-way NULL -> accepted_pdcp_log_id transition is allowed',
                    TG_TABLE_SCHEMA
                    USING ERRCODE = '42501';
            END IF;
            IF OLD.observation_id IS DISTINCT FROM NEW.observation_id
               OR OLD.observation_bundle_id IS DISTINCT FROM NEW.observation_bundle_id
               OR OLD.bundle_ordinal IS DISTINCT FROM NEW.bundle_ordinal
               OR OLD.target_file_id IS DISTINCT FROM NEW.target_file_id
               OR OLD.editing_cycle_id IS DISTINCT FROM NEW.editing_cycle_id
               OR OLD.target_version IS DISTINCT FROM NEW.target_version
               OR OLD.target_current_hash IS DISTINCT FROM NEW.target_current_hash
               OR OLD.waymark_engine_version IS DISTINCT FROM NEW.waymark_engine_version
               OR OLD.language IS DISTINCT FROM NEW.language
               OR OLD.symbol_name IS DISTINCT FROM NEW.symbol_name
               OR OLD.symbol_kind IS DISTINCT FROM NEW.symbol_kind
               OR OLD.symbol_parent IS DISTINCT FROM NEW.symbol_parent
               OR OLD.start_line IS DISTINCT FROM NEW.start_line
               OR OLD.start_column IS DISTINCT FROM NEW.start_column
               OR OLD.end_line IS DISTINCT FROM NEW.end_line
               OR OLD.end_column IS DISTINCT FROM NEW.end_column
               OR OLD.scope_start IS DISTINCT FROM NEW.scope_start
               OR OLD.scope_end IS DISTINCT FROM NEW.scope_end
               OR OLD.observed_scope_hash IS DISTINCT FROM NEW.observed_scope_hash
               OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
                RAISE EXCEPTION 'Immutable audit table %.target_scope_observations: non-linkage columns cannot be modified',
                    TG_TABLE_SCHEMA
                    USING ERRCODE = '42501';
            END IF;
            EXECUTE format(
                'SELECT EXISTS (
                    SELECT 1 FROM %I.append_only_pdcp_logs l
                    WHERE l.pdcp_log_id = $1
                      AND l.status = ''accepted''
                      AND l.target_file_id = $2
                      AND l.editing_cycle_id = $3
                      AND l.before_version = $4
                      AND l.before_hash = $5
                )',
                TG_TABLE_SCHEMA
            )
            INTO valid_log
            USING NEW.accepted_pdcp_log_id, NEW.target_file_id, NEW.editing_cycle_id, NEW.target_version, NEW.target_current_hash;

            IF NOT coalesce(valid_log, false) THEN
                RAISE EXCEPTION 'Immutable audit table %.target_scope_observations: accepted_pdcp_log_id % does not match an accepted log for this target/cycle/version/hash',
                    TG_TABLE_SCHEMA, NEW.accepted_pdcp_log_id
                    USING ERRCODE = '42501';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )

    op.execute("DROP TRIGGER IF EXISTS trg_immutable_target_scope_observations ON target_scope_observations;")
    op.execute(
        """
        CREATE TRIGGER trg_immutable_target_scope_observations
        BEFORE INSERT OR UPDATE OR DELETE ON target_scope_observations
        FOR EACH ROW
        EXECUTE FUNCTION patchdiff_enforce_scope_observation_immutability();
        """
    )

    # 3. Monotonic history_revision increment trigger on accepted logs and linked observations
    op.execute(
        """
        CREATE OR REPLACE FUNCTION patchdiff_bump_target_history_revision()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            IF TG_TABLE_NAME = 'append_only_pdcp_logs' THEN
                IF NEW.status = 'accepted' THEN
                    EXECUTE format(
                        'UPDATE %I.cloud_target_files SET history_revision = history_revision + 1 WHERE target_file_id = $1',
                        TG_TABLE_SCHEMA
                    ) USING NEW.target_file_id;
                END IF;
            ELSIF TG_TABLE_NAME = 'target_scope_observations' THEN
                IF OLD.accepted_pdcp_log_id IS NULL AND NEW.accepted_pdcp_log_id IS NOT NULL THEN
                    EXECUTE format(
                        'UPDATE %I.cloud_target_files SET history_revision = history_revision + 1 WHERE target_file_id = $1',
                        TG_TABLE_SCHEMA
                    ) USING NEW.target_file_id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )

    op.execute("DROP TRIGGER IF EXISTS trg_bump_history_revision_on_accepted_log ON append_only_pdcp_logs;")
    op.execute(
        """
        CREATE TRIGGER trg_bump_history_revision_on_accepted_log
        AFTER INSERT ON append_only_pdcp_logs
        FOR EACH ROW
        EXECUTE FUNCTION patchdiff_bump_target_history_revision();
        """
    )

    op.execute("DROP TRIGGER IF EXISTS trg_bump_history_revision_on_observation_link ON target_scope_observations;")
    op.execute(
        """
        CREATE TRIGGER trg_bump_history_revision_on_observation_link
        AFTER UPDATE OF accepted_pdcp_log_id ON target_scope_observations
        FOR EACH ROW
        EXECUTE FUNCTION patchdiff_bump_target_history_revision();
        """
    )

    # Trigger execution is owned by the migration; services cannot attach the
    # privileged revision function to their own temporary relations.
    op.execute("REVOKE ALL ON FUNCTION patchdiff_bump_target_history_revision() FROM PUBLIC")

    # SELECT FOR UPDATE otherwise requires a raw UPDATE grant on receipts.
    # Expose only this lock capability to the host, never receipt mutation.
    op.execute(
        """
        DO $install$
        DECLARE sch text := current_schema();
        BEGIN
            EXECUTE format($ddl$
                CREATE FUNCTION %I.patchdiff_lock_finalized_export(receipt_id uuid)
                RETURNS void LANGUAGE plpgsql SECURITY DEFINER
                SET search_path = pg_catalog, pg_temp
                AS $body$
                BEGIN
                    PERFORM 1 FROM %I.target_finalizations
                    WHERE finalization_id = receipt_id FOR UPDATE;
                END;
                $body$;
            $ddl$, sch, sch);
            EXECUTE format('REVOKE ALL ON FUNCTION %I.patchdiff_lock_finalized_export(uuid) FROM PUBLIC', sch);
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='patchdiff_host') THEN
                EXECUTE format('GRANT EXECUTE ON FUNCTION %I.patchdiff_lock_finalized_export(uuid) TO patchdiff_host', sch);
            END IF;
        END;
        $install$;
        """
    )

    # 4. Enforce explicit least-privilege grants when service roles exist
    op.execute(
        """
        DO $$
        DECLARE
            sch text := current_schema();
            relation record;
            principal text;
            sequence_name text;
        BEGIN
            EXECUTE format('REVOKE CREATE ON SCHEMA %I FROM PUBLIC', sch);
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM PUBLIC', sch);
            EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM PUBLIC', sch);

            FOR relation IN
                SELECT c.relname, string_agg(quote_ident(a.attname), ', ' ORDER BY a.attnum) AS columns
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
                WHERE n.nspname=sch AND c.relkind IN ('r','p') GROUP BY c.relname
            LOOP
                FOREACH principal IN ARRAY ARRAY['patchdiff_host','patchdiff_agent'] LOOP
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=principal) THEN
                        EXECUTE format('REVOKE ALL (%s) ON TABLE %I.%I FROM %I', relation.columns, sch, relation.relname, principal);
                    END IF;
                END LOOP;
            END LOOP;
            FOREACH principal IN ARRAY ARRAY['patchdiff_host','patchdiff_agent'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=principal) THEN
                    EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM %I',sch,principal);
                    FOREACH sequence_name IN ARRAY ARRAY['append_only_pdcp_logs_log_sequence_seq','append_only_manifest_ledger_ledger_sequence_seq'] LOOP
                        EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %I.%I TO %I',sch,sequence_name,principal);
                    END LOOP;
                END IF;
            END LOOP;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'patchdiff_agent') THEN
                EXECUTE format('GRANT USAGE ON SCHEMA %I TO patchdiff_agent', sch);
                EXECUTE format('REVOKE CREATE ON SCHEMA %I FROM patchdiff_agent', sch);
                EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM patchdiff_agent', sch);


                EXECUTE format(
                    'GRANT SELECT ON TABLE %I.users, %I.projects, %I.project_memberships, %I.cloud_target_files, '
                    '%I.target_snapshots, %I.editing_cycles, %I.append_only_pdcp_logs, %I.append_only_manifest_ledger, '
                    '%I.current_pdcp_files, %I.target_scope_observations TO patchdiff_agent',
                    sch, sch, sch, sch, sch, sch, sch, sch, sch, sch
                );
                EXECUTE format(
                    'GRANT INSERT ON TABLE %I.target_scope_observations, %I.append_only_pdcp_logs, '
                    '%I.append_only_manifest_ledger, %I.current_pdcp_files TO patchdiff_agent',
                    sch, sch, sch, sch
                );
                EXECUTE format(
                    'GRANT UPDATE (current_content, current_hash, version, latest_accepted_pdcp_log_id, updated_at) '
                    'ON TABLE %I.cloud_target_files TO patchdiff_agent',
                    sch
                );
                EXECUTE format(
                    'GRANT UPDATE (accepted_pdcp_log_id) ON TABLE %I.target_scope_observations TO patchdiff_agent',
                    sch
                );
                EXECUTE format(
                    'GRANT UPDATE (editing_cycle_id, protocol_version, pdcp_content, pdcp_content_hash, status, '
                    'submission_source, parent_pdcp_log_id, regeneration_attempt, regeneration_source, '
                    'last_pdcp_log_id, updated_at) ON TABLE %I.current_pdcp_files TO patchdiff_agent',
                    sch
                );
                IF to_regclass(format('%I.alembic_version', sch)) IS NOT NULL THEN
                    EXECUTE format('REVOKE ALL ON TABLE %I.alembic_version FROM patchdiff_agent', sch);
                END IF;
            END IF;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'patchdiff_host') THEN
                EXECUTE format('GRANT USAGE ON SCHEMA %I TO patchdiff_host', sch);
                EXECUTE format('REVOKE CREATE ON SCHEMA %I FROM patchdiff_host', sch);
                EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM patchdiff_host', sch);


                EXECUTE format(
                    'GRANT SELECT, INSERT ON TABLE %I.users, %I.projects, %I.project_memberships, %I.cloud_target_files, '
                    '%I.target_snapshots, %I.editing_cycles, %I.append_only_pdcp_logs, %I.append_only_manifest_ledger, '
                    '%I.current_pdcp_files, %I.target_scope_observations, %I.target_finalizations, '
                    '%I.target_finalization_export_chunks TO patchdiff_host',
                    sch, sch, sch, sch, sch, sch, sch, sch, sch, sch, sch, sch
                );
                EXECUTE format(
                    'GRANT UPDATE (current_content, current_hash, version, active_editing_cycle_id, '
                    'latest_accepted_pdcp_log_id, initial_snapshot_id, updated_at) '
                    'ON TABLE %I.cloud_target_files TO patchdiff_host',
                    sch
                );
                EXECUTE format(
                    'GRANT UPDATE (status, closed_at, closed_by_user_id, save_snapshot_id) '
                    'ON TABLE %I.editing_cycles TO patchdiff_host',
                    sch
                );
                EXECUTE format(
                    'GRANT UPDATE (editing_cycle_id, protocol_version, pdcp_content, pdcp_content_hash, status, '
                    'submission_source, parent_pdcp_log_id, regeneration_attempt, regeneration_source, '
                    'last_pdcp_log_id, updated_at) ON TABLE %I.current_pdcp_files TO patchdiff_host',
                    sch
                );
                EXECUTE format(
                    'GRANT UPDATE (accepted_pdcp_log_id) ON TABLE %I.target_scope_observations TO patchdiff_host',
                    sch
                );
                EXECUTE format(
                    'GRANT UPDATE (display_name, updated_at) ON TABLE %I.users TO patchdiff_host',
                    sch
                );
                EXECUTE format(
                    'GRANT UPDATE (name, updated_at) ON TABLE %I.projects TO patchdiff_host',
                    sch
                );
                IF to_regclass(format('%I.alembic_version', sch)) IS NOT NULL THEN
                    EXECUTE format('REVOKE ALL ON TABLE %I.alembic_version FROM patchdiff_host', sch);
                END IF;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM target_finalization_export_chunks) THEN
                RAISE EXCEPTION 'Cannot downgrade 20261101_0008: finalized export chunks exist';
            END IF;
        END $$;
        """
    )
    op.execute("DROP FUNCTION IF EXISTS patchdiff_lock_finalized_export(uuid)")
    op.execute("DROP TRIGGER IF EXISTS trg_bump_history_revision_on_observation_link ON target_scope_observations;")
    op.execute("DROP TRIGGER IF EXISTS trg_bump_history_revision_on_accepted_log ON append_only_pdcp_logs;")
    op.execute("DROP FUNCTION IF EXISTS patchdiff_bump_target_history_revision();")
    op.execute("DROP TRIGGER IF EXISTS trg_immutable_target_scope_observations ON target_scope_observations;")
    op.execute("DROP FUNCTION IF EXISTS patchdiff_enforce_scope_observation_immutability();")
    for tbl in (
        "target_finalization_export_chunks",
        "target_snapshots",
        "append_only_manifest_ledger",
        "append_only_pdcp_logs",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_immutable_{tbl} ON {tbl};")
    op.execute("DROP FUNCTION IF EXISTS patchdiff_enforce_immutable_audit_row();")
    op.drop_table("target_finalization_export_chunks")
    op.drop_column("cloud_target_files", "history_revision")
