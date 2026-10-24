"""Frozen initial schema; later model changes belong in subsequent migrations."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Create the original operational tables and geographic indexes."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        "resources",
        sa.Column("name", sa.String(), primary_key=False, nullable=False),
        sa.Column("category", sa.String(), primary_key=False, nullable=False),
        sa.Column("location", sa.String(), primary_key=False, nullable=False),
        sa.Column("latitude", sa.Float(), primary_key=False, nullable=False),
        sa.Column("longitude", sa.Float(), primary_key=False, nullable=False),
        sa.Column("capacity", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("occupancy", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("accessible", sa.Boolean(), primary_key=False, nullable=False),
        sa.Column("pet_friendly", sa.Boolean(), primary_key=False, nullable=False),
        sa.Column("contact", sa.String(), primary_key=False, nullable=False),
        sa.Column("published", sa.Boolean(), primary_key=False, nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column("version", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_table(
        "simulation",
        sa.Column("running", sa.Boolean(), primary_key=False, nullable=False),
        sa.Column("cursor", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("speed", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column("worker_heartbeat", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("name", sa.String(), primary_key=False, nullable=False),
        sa.Column("role", sa.String(), primary_key=False, nullable=False),
        sa.Column("token_hash", sa.String(), primary_key=False, nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "incidents",
        sa.Column("title", sa.String(), primary_key=False, nullable=False),
        sa.Column("category", sa.String(), primary_key=False, nullable=False),
        sa.Column("severity", sa.String(), primary_key=False, nullable=False),
        sa.Column("status", sa.String(), primary_key=False, nullable=False),
        sa.Column("latitude", sa.Float(), primary_key=False, nullable=False),
        sa.Column("longitude", sa.Float(), primary_key=False, nullable=False),
        sa.Column("location", sa.String(), primary_key=False, nullable=False),
        sa.Column("summary", sa.String(), primary_key=False, nullable=False),
        sa.Column(
            "assigned_to", sa.Uuid(as_uuid=False), sa.ForeignKey("users.id"), primary_key=False, nullable=True
        ),
        sa.Column(
            "merged_into",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("incidents.id"),
            primary_key=False,
            nullable=True,
        ),
        sa.Column("version", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("simulation", sa.Boolean(), primary_key=False, nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_table(
        "reports",
        sa.Column(
            "user_id", sa.Uuid(as_uuid=False), sa.ForeignKey("users.id"), primary_key=False, nullable=False
        ),
        sa.Column("category", sa.String(), primary_key=False, nullable=False),
        sa.Column("description", sa.String(), primary_key=False, nullable=False),
        sa.Column("latitude", sa.Float(), primary_key=False, nullable=False),
        sa.Column("longitude", sa.Float(), primary_key=False, nullable=False),
        sa.Column("location", sa.String(), primary_key=False, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.Column("photo", sa.String(), primary_key=False, nullable=True),
        sa.Column("source", sa.String(), primary_key=False, nullable=False),
        sa.Column("status", sa.String(), primary_key=False, nullable=False),
        sa.Column("simulation", sa.Boolean(), primary_key=False, nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_table(
        "agent_runs",
        sa.Column(
            "report_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("reports.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column(
            "incident_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("incidents.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("stage", sa.String(), primary_key=False, nullable=False),
        sa.Column("status", sa.String(), primary_key=False, nullable=False),
        sa.Column("attempts", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column("input", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("output", sa.JSON(), primary_key=False, nullable=True),
        sa.Column("error", sa.String(), primary_key=False, nullable=True),
        sa.Column("remote_id", sa.String(), primary_key=False, nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_table(
        "coordinator_actions",
        sa.Column(
            "user_id", sa.Uuid(as_uuid=False), sa.ForeignKey("users.id"), primary_key=False, nullable=False
        ),
        sa.Column(
            "incident_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("incidents.id"),
            primary_key=False,
            nullable=True,
        ),
        sa.Column("action", sa.String(), primary_key=False, nullable=False),
        sa.Column("details", sa.String(), primary_key=False, nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_table(
        "evidence",
        sa.Column(
            "incident_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("incidents.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column(
            "report_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("reports.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("text", sa.String(), primary_key=False, nullable=False),
        sa.Column("source", sa.String(), primary_key=False, nullable=False),
        sa.Column("uncertainty", sa.String(), primary_key=False, nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_table(
        "incident_reports",
        sa.Column(
            "incident_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("incidents.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column(
            "report_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("reports.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint("incident_id", "report_id"),
    )
    op.create_table(
        "incident_subscriptions",
        sa.Column(
            "user_id", sa.Uuid(as_uuid=False), sa.ForeignKey("users.id"), primary_key=False, nullable=False
        ),
        sa.Column(
            "incident_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("incidents.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint("user_id", "incident_id"),
    )
    op.create_table(
        "public_updates",
        sa.Column(
            "incident_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("incidents.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("title", sa.String(), primary_key=False, nullable=False),
        sa.Column("body", sa.String(), primary_key=False, nullable=False),
        sa.Column("audience", sa.String(), primary_key=False, nullable=False),
        sa.Column("status", sa.String(), primary_key=False, nullable=False),
        sa.Column(
            "author_id", sa.Uuid(as_uuid=False), sa.ForeignKey("users.id"), primary_key=False, nullable=False
        ),
        sa.Column(
            "approved_by", sa.Uuid(as_uuid=False), sa.ForeignKey("users.id"), primary_key=False, nullable=True
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), primary_key=False, nullable=True),
        sa.Column("latitude", sa.Float(), primary_key=False, nullable=False),
        sa.Column("longitude", sa.Float(), primary_key=False, nullable=False),
        sa.Column("category", sa.String(), primary_key=False, nullable=False),
        sa.Column("severity", sa.String(), primary_key=False, nullable=False),
        sa.Column("simulation", sa.Boolean(), primary_key=False, nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_table(
        "resource_requests",
        sa.Column(
            "incident_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("incidents.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column(
            "resource_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("resources.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("status", sa.String(), primary_key=False, nullable=False),
        sa.Column("rationale", sa.String(), primary_key=False, nullable=False),
        sa.Column(
            "approved_by", sa.Uuid(as_uuid=False), sa.ForeignKey("users.id"), primary_key=False, nullable=True
        ),
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_table(
        "agent_findings",
        sa.Column(
            "run_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("agent_runs.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column(
            "incident_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("incidents.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("assessment", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint("run_id"),
    )
    if op.get_bind().dialect.name == "postgresql":
        for table in ("incidents", "resources"):
            op.execute(
                f"CREATE INDEX ix_{table}_location ON {table} USING gist ((ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography))"
            )


def downgrade():
    """Drop only the original tables when explicitly reverting this revision."""
    op.drop_table("agent_findings")
    op.drop_table("resource_requests")
    op.drop_table("public_updates")
    op.drop_table("incident_subscriptions")
    op.drop_table("incident_reports")
    op.drop_table("evidence")
    op.drop_table("coordinator_actions")
    op.drop_table("agent_runs")
    op.drop_table("reports")
    op.drop_table("incidents")
    op.drop_table("users")
    op.drop_table("simulation")
    op.drop_table("resources")
