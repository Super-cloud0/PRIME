"""Add telegram_chat_id/reminders_enabled/last_reminder_at to user for weekly check-in reminders.

Revision ID: 0003_weekly_reminders
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_weekly_reminders"
down_revision = "0002_face_photo"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user", sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True))
    op.add_column("user", sa.Column("reminders_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("user", sa.Column("last_reminder_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_user_telegram_chat_id", "user", ["telegram_chat_id"])


def downgrade():
    op.drop_index("ix_user_telegram_chat_id", table_name="user")
    op.drop_column("user", "last_reminder_at")
    op.drop_column("user", "reminders_enabled")
    op.drop_column("user", "telegram_chat_id")
