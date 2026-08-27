"""Add photo_path to face_analysis for the weekly progress view.

Revision ID: 0002_face_photo
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_face_photo"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("face_analysis", sa.Column("photo_path", sa.String(100), nullable=True))


def downgrade():
    op.drop_column("face_analysis", "photo_path")
