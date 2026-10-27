"""Add observation bundles; preserve historical single-observation linkage.

Revision ID: 20261027_0005
Revises: 20261026_0004
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261027_0005"
down_revision = "20261026_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("target_scope_observations", sa.Column("observation_bundle_id", postgresql.UUID(as_uuid=True)))
    op.add_column("target_scope_observations", sa.Column("bundle_ordinal", sa.Integer()))
    op.create_check_constraint("ck_scope_bundle_pair", "target_scope_observations",
                               "(observation_bundle_id IS NULL AND bundle_ordinal IS NULL) OR "
                               "(observation_bundle_id IS NOT NULL AND bundle_ordinal IS NOT NULL AND bundle_ordinal >= 0 AND bundle_ordinal < 32)")
    op.create_unique_constraint("uq_scope_bundle_ordinal", "target_scope_observations", ["observation_bundle_id", "bundle_ordinal"])
    op.create_index("ix_scope_bundle", "target_scope_observations", ["observation_bundle_id"])
    op.create_index("ix_scope_accepted_log", "target_scope_observations", ["accepted_pdcp_log_id"])
    op.drop_constraint("uq_target_scope_observations_accepted_log", "target_scope_observations", type_="unique")
    op.create_index("uq_scope_single_accepted_log", "target_scope_observations", ["accepted_pdcp_log_id"], unique=True,
                    postgresql_where=sa.text("observation_bundle_id IS NULL AND accepted_pdcp_log_id IS NOT NULL"))


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM target_scope_observations WHERE observation_bundle_id IS NOT NULL)
           OR EXISTS (SELECT 1 FROM target_scope_observations WHERE accepted_pdcp_log_id IS NOT NULL
                      GROUP BY accepted_pdcp_log_id HAVING count(*) > 1)
           OR EXISTS (SELECT 1 FROM append_only_pdcp_logs WHERE protocol_version = 'patchdiff-observed-batch/1' AND status = 'accepted') THEN
            RAISE EXCEPTION 'Cannot downgrade 20261027_0005: bundled observations or accepted batch evidence exist';
        END IF;
    END $$;""")
    op.drop_index("uq_scope_single_accepted_log", table_name="target_scope_observations")
    op.create_unique_constraint("uq_target_scope_observations_accepted_log", "target_scope_observations", ["accepted_pdcp_log_id"])
    op.drop_index("ix_scope_accepted_log", table_name="target_scope_observations")
    op.drop_index("ix_scope_bundle", table_name="target_scope_observations")
    op.drop_constraint("uq_scope_bundle_ordinal", "target_scope_observations", type_="unique")
    op.drop_constraint("ck_scope_bundle_pair", "target_scope_observations", type_="check")
    op.drop_column("target_scope_observations", "bundle_ordinal")
    op.drop_column("target_scope_observations", "observation_bundle_id")
