"""Initial PRIME production schema.

Revision ID: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("elo", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("prime_score", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("wins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("losses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("games", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_user_email"),
    )
    op.create_index("ix_user_email", "user", ["email"], unique=True)
    op.create_table(
        "face_analysis",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("analysis_type", sa.String(20), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("tips_json", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_face_analysis_user_id", "face_analysis", ["user_id"])
    op.create_table(
        "elo_match",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("winner_id", sa.String(36), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("loser_id", sa.String(36), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("winner_elo_before", sa.Integer(), nullable=False),
        sa.Column("loser_elo_before", sa.Integer(), nullable=False),
        sa.Column("winner_delta", sa.Integer(), nullable=False),
        sa.Column("loser_delta", sa.Integer(), nullable=False),
        sa.Column("opponent_name", sa.String(50), nullable=False),
        sa.Column("is_bot", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "music_track",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("stored_name", sa.String(100), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("stored_name", name="uq_music_stored_name"),
    )
    op.create_index("ix_music_track_user_id", "music_track", ["user_id"])


def downgrade():
    op.drop_index("ix_music_track_user_id", table_name="music_track")
    op.drop_table("music_track")
    op.drop_table("elo_match")
    op.drop_index("ix_face_analysis_user_id", table_name="face_analysis")
    op.drop_table("face_analysis")
    op.drop_index("ix_user_email", table_name="user")
    op.drop_table("user")
