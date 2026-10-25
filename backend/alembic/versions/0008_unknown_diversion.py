"""Keep unknown hospital diversion distinct from accepting patients."""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    """Allow unknown diversion without fabricating an accepting status."""
    with op.batch_alter_table("hospitals") as batch:
        batch.alter_column("diversion", existing_type=sa.Boolean(), nullable=True)


def downgrade():
    """Restore the legacy non-null representation when explicitly rolling back."""
    op.execute("UPDATE hospitals SET diversion = false WHERE diversion IS NULL")
    with op.batch_alter_table("hospitals") as batch:
        batch.alter_column("diversion", existing_type=sa.Boolean(), nullable=False)
