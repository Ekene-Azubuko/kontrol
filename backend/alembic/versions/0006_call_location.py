"""Preserve automatically detected call locations independently of reviewed locations."""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    """Add nullable inference provenance; workers enrich previously transcribed calls in place."""
    op.add_column("calls", sa.Column("detected_location", sa.JSON(), nullable=True))


def downgrade():
    """Remove the derived metadata while retaining original recordings and review history."""
    op.drop_column("calls", "detected_location")
