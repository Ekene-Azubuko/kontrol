"""Add live telephony alongside existing uploaded recordings."""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    """Preserve all recordings and add independent live-session and segment storage."""
    op.add_column("calls", sa.Column("source", sa.String(), nullable=False, server_default="recording"))
    with op.batch_alter_table("calls") as batch:
        batch.alter_column("audio_key", existing_type=sa.String(), nullable=True)
    op.create_table(
        "live_call_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("call_id", sa.Uuid(), sa.ForeignKey("calls.id", ondelete="SET NULL"), unique=True),
        sa.Column("provider_sid", sa.String(), nullable=False, unique=True),
        sa.Column("browser_sid", sa.String()),
        sa.Column("caller", sa.String(), nullable=False),
        sa.Column("called", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("answered_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("stream_sid", sa.String()),
        sa.Column("stream_closed_at", sa.DateTime(timezone=True)),
        sa.Column("stream_heartbeat", sa.DateTime(timezone=True)),
        sa.Column("transcription_error", sa.String()),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_text", sa.String()),
        sa.Column("recording_sid", sa.String()),
        sa.Column("recording_state", sa.String(), nullable=False),
        sa.Column("recording_attempts", sa.Integer(), nullable=False),
        sa.Column("recording_claimed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "live_transcript_segments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("call_id", sa.Uuid(), sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("track", sa.String(), nullable=False),
        sa.Column("item_id", sa.String(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("finalized", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("call_id", "track", "item_id"),
    )
    op.create_index("ix_live_transcript_segments_call_id", "live_transcript_segments", ["call_id"])


def downgrade():
    """Refuse to discard live-call provenance or rewrite missing recordings."""
    if (op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM calls WHERE source = 'live'"))
            or op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM live_call_sessions"))):
        raise RuntimeError("Archive live calls before downgrading")
    op.drop_table("live_transcript_segments")
    op.drop_table("live_call_sessions")
    with op.batch_alter_table("calls") as batch:
        batch.alter_column("audio_key", existing_type=sa.String(), nullable=False)
        batch.drop_column("source")
