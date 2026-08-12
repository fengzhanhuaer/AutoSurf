from __future__ import annotations

from importlib.resources import files

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


INITIAL_REVISION = "0001_initial"
HEAD_REVISION = "0002_cookiecloud_import"
CORE_TABLES = {"credentials", "automations", "executions", "cookiecloud_blobs"}


def upgrade_database(database_url: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(files("autosurf.migrations")))
    config.set_main_option("sqlalchemy.url", database_url)
    _adopt_unversioned_database(config, database_url)
    command.upgrade(config, "head")


def _adopt_unversioned_database(config: Config, database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        if "alembic_version" in tables or not tables:
            return
        present_core = tables & CORE_TABLES
        if present_core != CORE_TABLES:
            missing = ", ".join(sorted(CORE_TABLES - present_core))
            raise RuntimeError(f"cannot migrate an unversioned partial database; missing tables: {missing}")

        execution_columns = {item["name"] for item in inspector.get_columns("executions")}
        has_snapshot = "credential_payload" in execution_columns
        has_sources = "cookiecloud_sources" in tables
        if has_snapshot != has_sources:
            raise RuntimeError("cannot migrate an inconsistent database: CookieCloud migration is partially applied")
        command.stamp(config, HEAD_REVISION if has_snapshot else INITIAL_REVISION)
    finally:
        engine.dispose()
