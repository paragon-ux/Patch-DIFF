"""record source line endings for uploaded targets

Adds nullable JSONB `cloud_target_files.source_line_endings`. New uploads record
the raw upload's line-ending counts, style, size and SHA-256 before canonical LF
normalization, so exports can restore a uniform original style. Existing targets
keep NULL (unknown): the raw upload was never stored, so nothing is backfilled.

Canonical content, hashes, history and replay are unchanged. Downgrade refuses
while any recorded line-ending facts exist; recorded facts are never discarded to
make a downgrade succeed.

Revision ID: 20261022_0003
Revises: 20261020_0002
Create Date: 2026-10-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261022_0003"
down_revision: Union[str, None] = "20261020_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cloud_target_files",
        sa.Column("source_line_endings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM cloud_target_files WHERE source_line_endings IS NOT NULL) THEN
                RAISE EXCEPTION 'Cannot downgrade 20261022_0003: recorded source line endings exist';
            END IF;
        END $$;
        """
    )
    op.drop_column("cloud_target_files", "source_line_endings")
