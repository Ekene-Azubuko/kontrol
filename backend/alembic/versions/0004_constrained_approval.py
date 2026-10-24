"""Preserve unknown patient counts and track actual reservations during constrained approval."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    """Separate proposed patient counts from confirmed reservations without resetting active responses."""
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("dispatch_assignments")}
    with op.batch_alter_table("dispatch_assignments") as batch:
        batch.alter_column("patients", existing_type=sa.Integer(), nullable=True)
        if "reserved_beds" not in columns:
            batch.add_column(sa.Column("reserved_beds", sa.Integer(), nullable=False, server_default="0"))
    if "reserved_beds" not in columns:
        # Earlier versions reserved every allocated bed until arrival; retain those in-flight commitments.
        op.execute(sa.text("""
            UPDATE dispatch_assignments SET reserved_beds = COALESCE(patients, 0)
            WHERE hospital_id IS NOT NULL AND released_at IS NULL
            AND status NOT IN ('completed', 'cancelled')
        """))


def downgrade():
    """Restore the old schema only when doing so cannot erase unknown patient counts."""
    unknown = op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM dispatch_assignments WHERE patients IS NULL"))
    if unknown:
        raise RuntimeError("Cannot downgrade while dispatch assignments have unknown patient counts")
    with op.batch_alter_table("dispatch_assignments") as batch:
        batch.drop_column("reserved_beds")
        batch.alter_column("patients", existing_type=sa.Integer(), nullable=False)
