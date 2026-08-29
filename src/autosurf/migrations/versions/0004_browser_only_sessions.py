"""Remove synchronized credential storage.

Revision ID: 0004_browser_only_sessions
Revises: 0003_system_settings
"""
from alembic import op


revision = "0004_browser_only_sessions"
down_revision = "0003_system_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("automations") as batch_op:
        batch_op.drop_column("credential_id")
    with op.batch_alter_table("executions") as batch_op:
        batch_op.drop_column("credential_payload")
        batch_op.drop_column("credential_version")
    op.drop_table("cookiecloud_sources")
    op.drop_table("cookiecloud_blobs")
    op.drop_index("ix_credentials_domain", table_name="credentials")
    op.drop_table("credentials")


def downgrade() -> None:
    raise RuntimeError("browser-only credential migration cannot be downgraded")
