"""Add per-execution configuration overrides.

Revision ID: 0005_execution_config_override
Revises: 0004_browser_only_sessions
"""
from alembic import op
import sqlalchemy as sa


revision = "0005_execution_config_override"
down_revision = "0004_browser_only_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("executions") as batch_op:
        batch_op.add_column(sa.Column("config_override_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("executions") as batch_op:
        batch_op.drop_column("config_override_json")
