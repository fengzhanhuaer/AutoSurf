from __future__ import annotations

from importlib.resources import files

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


INITIAL_REVISION = "0001_initial"
COOKIECLOUD_REVISION = "0002_cookiecloud_import"
SYSTEM_SETTINGS_REVISION = "0003_system_settings"
BROWSER_ONLY_REVISION = "0004_browser_only_sessions"
HEAD_REVISION = "0005_execution_config_override"
LEGACY_CORE_TABLES = {"credentials", "automations", "executions", "cookiecloud_blobs"}
BROWSER_ONLY_CORE_TABLES = {"automations", "executions", "system_settings"}


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
        if BROWSER_ONLY_CORE_TABLES.issubset(tables) and not (
            {"credentials", "cookiecloud_blobs", "cookiecloud_sources"} & tables
        ):
            execution_columns = {item["name"] for item in inspector.get_columns("executions")}
            revision = HEAD_REVISION if "config_override_json" in execution_columns else BROWSER_ONLY_REVISION
            command.stamp(config, revision)
            return
        present_core = tables & LEGACY_CORE_TABLES
        if present_core != LEGACY_CORE_TABLES:
            missing = ", ".join(sorted(LEGACY_CORE_TABLES - present_core))
            raise RuntimeError(f"cannot migrate an unversioned partial database; missing tables: {missing}")

        execution_columns = {item["name"] for item in inspector.get_columns("executions")}
        has_snapshot = "credential_payload" in execution_columns
        has_sources = "cookiecloud_sources" in tables
        if has_snapshot != has_sources:
            raise RuntimeError("cannot migrate an inconsistent database: CookieCloud migration is partially applied")
        if not has_snapshot:
            command.stamp(config, INITIAL_REVISION)
        elif "system_settings" in tables:
            command.stamp(config, SYSTEM_SETTINGS_REVISION)
        else:
            command.stamp(config, COOKIECLOUD_REVISION)
    finally:
        engine.dispose()
