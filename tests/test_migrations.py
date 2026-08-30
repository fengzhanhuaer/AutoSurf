from datetime import datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from autosurf.infrastructure.migrations import (
    BROWSER_ONLY_REVISION,
    COOKIECLOUD_REVISION,
    HEAD_REVISION,
    INITIAL_REVISION,
    upgrade_database,
)


def migration_config(database_url: str) -> Config:
    from importlib.resources import files

    config = Config()
    config.set_main_option("script_location", str(files("autosurf.migrations")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def revision(database_url: str) -> str:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    finally:
        engine.dispose()


def test_empty_database_upgrades_to_head(tmp_path):
    url = f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"
    upgrade_database(url)
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {"automations", "executions", "system_settings"}.issubset(tables)
        assert not {"credentials", "cookiecloud_sources", "cookiecloud_blobs"} & tables
        assert "credential_id" not in {
            column["name"] for column in inspector.get_columns("automations")
        }
        execution_columns = {column["name"] for column in inspector.get_columns("executions")}
        assert "config_override_json" in execution_columns
        assert "credential_payload" not in execution_columns
        assert "credential_version" not in execution_columns
        assert revision(url) == HEAD_REVISION
    finally:
        engine.dispose()


def test_versioned_old_database_removes_legacy_credentials(tmp_path):
    url = f"sqlite:///{(tmp_path / 'old.db').as_posix()}"
    config = migration_config(url)
    command.upgrade(config, INITIAL_REVISION)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO credentials (id,name,provider,domain,encrypted_payload,version,updated_at) "
            "VALUES ('id-1','kept','manual','example.com','ciphertext',1,:now)"
        ), {"now": datetime(2026, 1, 1)})
    engine.dispose()

    upgrade_database(url)

    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "credentials" not in tables
        assert "automations" in tables
        assert "executions" in tables
        assert revision(url) == HEAD_REVISION
    finally:
        engine.dispose()


def test_unversioned_current_database_is_adopted(tmp_path):
    url = f"sqlite:///{(tmp_path / 'current.db').as_posix()}"
    config = migration_config(url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
    engine.dispose()

    upgrade_database(url)
    assert revision(url) == HEAD_REVISION


def test_unversioned_browser_only_database_adds_execution_overrides(tmp_path):
    url = f"sqlite:///{(tmp_path / 'browser-only.db').as_posix()}"
    config = migration_config(url)
    command.upgrade(config, BROWSER_ONLY_REVISION)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
    engine.dispose()

    upgrade_database(url)

    engine = create_engine(url)
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("executions")}
        assert "config_override_json" in columns
        assert revision(url) == HEAD_REVISION
    finally:
        engine.dispose()


def test_unversioned_cookiecloud_database_upgrades_to_head(tmp_path):
    url = f"sqlite:///{(tmp_path / 'cookiecloud.db').as_posix()}"
    config = migration_config(url)
    command.upgrade(config, COOKIECLOUD_REVISION)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
    engine.dispose()

    upgrade_database(url)

    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "system_settings" in tables
        assert not {"credentials", "cookiecloud_sources", "cookiecloud_blobs"} & tables
        assert revision(url) == HEAD_REVISION
    finally:
        engine.dispose()


def test_unversioned_partial_database_is_rejected(tmp_path):
    url = f"sqlite:///{(tmp_path / 'broken.db').as_posix()}"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE credentials (id VARCHAR(36) PRIMARY KEY)"))
    engine.dispose()

    with pytest.raises(RuntimeError, match="partial database"):
        upgrade_database(url)
