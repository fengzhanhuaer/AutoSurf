"""Add persistent system settings.

Revision ID: 0003_system_settings
Revises: 0002_cookiecloud_import
"""
from alembic import op
import sqlalchemy as sa


revision = "0003_system_settings"
down_revision = "0002_cookiecloud_import"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value_json", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("system_settings")
