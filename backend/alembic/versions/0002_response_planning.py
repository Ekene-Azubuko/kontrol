"""Add response planning without discarding reports or historical agent runs."""

from alembic import op
import sqlalchemy as sa
from app.db import Base
from app import models  # noqa: F401

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None
NEW_TABLES = [
    "hospitals",
    "hospital_inventory",
    "emergency_vehicles",
    "response_plans",
    "proposed_assignments",
    "dispatch_assignments",
    "communication_logs",
]


def upgrade():
    """Extend existing observations and add the response lifecycle tables."""
    op.add_column("reports", sa.Column("reported_casualties", sa.Integer(), nullable=True))
    op.add_column("incidents", sa.Column("reported_casualties", sa.Integer(), nullable=True))
    op.add_column(
        "incidents", sa.Column("response_status", sa.String(), nullable=False, server_default="unplanned")
    )
    for name in NEW_TABLES:
        Base.metadata.tables[name].create(op.get_bind())
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("plan_id", sa.Uuid(as_uuid=False), nullable=True))
        batch.create_foreign_key("fk_agent_run_plan", "response_plans", ["plan_id"], ["id"])
        batch.create_unique_constraint("uq_plan_stage", ["plan_id", "stage"])
        batch.create_index("ix_agent_runs_plan_id", ["plan_id"])
    # Old unfinished jobs use a different output contract; preserve them as cancelled history.
    op.execute(
        "UPDATE agent_runs SET status='cancelled', error='Legacy workflow retired by response-planning migration' WHERE status IN ('queued', 'running')"
    )


def downgrade():
    """Remove the pivot schema only when an operator explicitly requests rollback."""
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_index("ix_agent_runs_plan_id")
        batch.drop_constraint("uq_plan_stage", type_="unique")
        batch.drop_constraint("fk_agent_run_plan", type_="foreignkey")
        batch.drop_column("plan_id")
    for name in reversed(NEW_TABLES):
        op.drop_table(name)
    op.drop_column("incidents", "response_status")
    op.drop_column("incidents", "reported_casualties")
    op.drop_column("reports", "reported_casualties")
