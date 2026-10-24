"""Store richer CREAO results without replacing existing response records."""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    """Add raw responses, discovery provenance, nullable capacity, and ETA metadata."""
    inspector = sa.inspect(op.get_bind())
    def columns(table):
        """Read the current columns so fresh and upgraded databases follow one migration path."""
        return {column["name"] for column in inspector.get_columns(table)}
    if "raw_response" not in columns("agent_runs"):
        op.add_column("agent_runs", sa.Column("raw_response", sa.JSON(), nullable=True))
    if "source_urls" not in columns("hospitals"):
        op.add_column("hospitals", sa.Column("source_urls", sa.JSON(), nullable=False, server_default="[]"))
    if "discovered_by_agent" not in columns("hospitals"):
        op.add_column(
            "hospitals",
            sa.Column("discovered_by_agent", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    with op.batch_alter_table("hospitals") as batch:
        batch.alter_column("total_beds", existing_type=sa.Integer(), nullable=True)
        batch.alter_column("occupied_beds", existing_type=sa.Integer(), nullable=True)
        batch.alter_column("baseline_occupied", existing_type=sa.Integer(), nullable=True)
    assignment_columns = columns("proposed_assignments")
    with op.batch_alter_table("proposed_assignments") as batch:
        batch.alter_column("patients", existing_type=sa.Integer(), nullable=True)
        if "vehicle_eta_method" not in assignment_columns:
            batch.add_column(
                sa.Column(
                    "vehicle_eta_method",
                    sa.String(),
                    nullable=False,
                    server_default="coordinate_estimate",
                )
            )
        if "hospital_eta_method" not in assignment_columns:
            batch.add_column(sa.Column("hospital_eta_method", sa.String(), nullable=True))
        if "response_role" not in assignment_columns:
            batch.add_column(
                sa.Column("response_role", sa.String(), nullable=False, server_default="response")
            )


def downgrade():
    """Remove only fields introduced for the richer CREAO contracts."""
    with op.batch_alter_table("proposed_assignments") as batch:
        batch.drop_column("response_role")
        batch.drop_column("hospital_eta_method")
        batch.drop_column("vehicle_eta_method")
        batch.alter_column("patients", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("hospitals") as batch:
        batch.alter_column("baseline_occupied", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("occupied_beds", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("total_beds", existing_type=sa.Integer(), nullable=False)
    op.drop_column("hospitals", "discovered_by_agent")
    op.drop_column("hospitals", "source_urls")
    op.drop_column("agent_runs", "raw_response")
