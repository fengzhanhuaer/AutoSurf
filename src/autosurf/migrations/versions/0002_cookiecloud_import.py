"""Add execution credential snapshots and CookieCloud sources.

Revision ID: 0002_cookiecloud_import
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa


revision = "0002_cookiecloud_import"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("executions") as batch_op:
        batch_op.add_column(sa.Column("credential_payload", sa.Text(), nullable=True))
    op.create_table(
        "cookiecloud_sources",
        sa.Column("uuid", sa.String(128), primary_key=True),
        sa.Column("encrypted_password", sa.Text(), nullable=False),
        sa.Column("auto_import", sa.Boolean(), nullable=False),
        sa.Column("last_import_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("cookiecloud_sources")
    with op.batch_alter_table("executions") as batch_op:
        batch_op.drop_column("credential_payload")
