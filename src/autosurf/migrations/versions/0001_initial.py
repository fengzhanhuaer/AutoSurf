"""Initial AutoSurf schema.

Revision ID: 0001_initial
Revises: None
"""
from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_credentials_domain", "credentials", ["domain"])
    op.create_table(
        "automations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("handler_type", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("credential_id", sa.String(36), sa.ForeignKey("credentials.id"), nullable=True),
    )
    op.create_index("ix_automations_handler_type", "automations", ["handler_type"])
    op.create_index("ix_automations_next_run_at", "automations", ["next_run_at"])
    op.create_table(
        "executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("automation_id", sa.String(36), sa.ForeignKey("automations.id"), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("credential_version", sa.Integer(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_executions_automation_id", "executions", ["automation_id"])
    op.create_index("ix_executions_available_at", "executions", ["available_at"])
    op.create_index("ix_executions_status", "executions", ["status"])
    op.create_table(
        "cookiecloud_blobs",
        sa.Column("uuid", sa.String(128), primary_key=True),
        sa.Column("encrypted_data", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("cookiecloud_blobs")
    op.drop_index("ix_executions_status", table_name="executions")
    op.drop_index("ix_executions_available_at", table_name="executions")
    op.drop_index("ix_executions_automation_id", table_name="executions")
    op.drop_table("executions")
    op.drop_index("ix_automations_next_run_at", table_name="automations")
    op.drop_index("ix_automations_handler_type", table_name="automations")
    op.drop_table("automations")
    op.drop_index("ix_credentials_domain", table_name="credentials")
    op.drop_table("credentials")
