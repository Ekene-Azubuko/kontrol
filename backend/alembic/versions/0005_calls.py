"""Add private simulated calls without altering historical resident data."""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    """Create durable call intake and review provenance."""
    op.create_table(
        "calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sample_key", sa.String()),
        sa.Column("audio_key", sa.String(), nullable=False),
        sa.Column("audio_content_type", sa.String(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("caller_latitude", sa.Float()),
        sa.Column("caller_longitude", sa.Float()),
        sa.Column("caller_accuracy_m", sa.Float()),
        sa.Column("original_transcript", sa.String()),
        sa.Column("reviewed_transcript", sa.String()),
        sa.Column("confirmed_latitude", sa.Float()),
        sa.Column("confirmed_longitude", sa.Float()),
        sa.Column("confirmed_address", sa.String()),
        sa.Column("confirmed_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("report_id", sa.Uuid(), sa.ForeignKey("reports.id"), unique=True),
        sa.Column("simulation", sa.Boolean(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claim_token", sa.String()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("transcription_error", sa.String()),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index("ix_calls_status", "calls", ["status"])


def downgrade():
    """Refuse to erase call recordings' review history during rollback."""
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM calls")):
        raise RuntimeError("Archive calls before downgrading the call migration")
    op.drop_table("calls")
