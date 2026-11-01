"""Add materialized_state_checks to target_finalizations table.

Revision ID: 20261031_0007
Revises: 20261031_0006
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261031_0007"
down_revision: Union[str, None] = "20261031_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "target_finalizations",
        sa.Column("materialized_state_checks", postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("target_finalizations", "materialized_state_checks")
