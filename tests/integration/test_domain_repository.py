from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.engine import URL, make_url

DOMAIN_TABLES = {
    "bom_items",
    "drawings",
    "equipment",
    "materials",
    "project_tasks",
    "purchase_orders",
    "ship_systems",
    "ships",
    "suppliers",
}

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXPLICIT_DATABASE_URL_ATTRIBUTE = "shipyard_ai_explicit_database_url"


def _validated_test_database_url(raw_url: str) -> URL:
    url = make_url(raw_url)
    if url.database is None or not url.database.endswith("_test"):
        raise ValueError("TEST_DATABASE_URL must name a database ending in _test")
    return url


def _configured_test_database_url() -> URL:
    raw_url = os.getenv("TEST_DATABASE_URL")
    if raw_url is None:
        pytest.skip("TEST_DATABASE_URL is not configured")
    try:
        return _validated_test_database_url(raw_url)
    except ValueError as exc:
        pytest.fail(str(exc), pytrace=False)


def _alembic_config(url: URL) -> Config:
    config = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    rendered_url = url.render_as_string(hide_password=False).replace("%", "%%")
    config.set_main_option("sqlalchemy.url", rendered_url)
    config.attributes[EXPLICIT_DATABASE_URL_ATTRIBUTE] = True
    return config


def _validated_alembic_test_database_url(config: Config) -> URL:
    raw_url = config.get_main_option("sqlalchemy.url")
    if raw_url is None:
        raise ValueError("Alembic must have an explicitly configured test database")
    url = _validated_test_database_url(raw_url)
    if url.database != "shipyard_ai_test":
        raise ValueError("Alembic must target database shipyard_ai_test")
    return url


def test_test_database_url_rejects_non_test_database_without_leaking_secret() -> None:
    secret = "do-not-print"
    raw_url = f"postgresql+psycopg://shipyard:{secret}@localhost/shipyard_ai"

    with pytest.raises(ValueError) as captured:
        _validated_test_database_url(raw_url)

    assert str(captured.value) == (
        "TEST_DATABASE_URL must name a database ending in _test"
    )
    assert secret not in str(captured.value)


def test_explicit_alembic_test_url_takes_precedence_over_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = _configured_test_database_url()
    config = _alembic_config(url)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+missingdriver://invalid:invalid@127.0.0.1/shipyard_ai",
    )

    command.current(config)

    assert _validated_alembic_test_database_url(config) == url


def test_migration_upgrades_an_empty_postgresql_database() -> None:
    url = _configured_test_database_url()
    config = _alembic_config(url)
    engine = create_engine(url)
    try:
        _validated_alembic_test_database_url(config)
        command.downgrade(config, "base")
        assert DOMAIN_TABLES.isdisjoint(inspect(engine).get_table_names())

        command.upgrade(config, "head")

        table_names = set(inspect(engine).get_table_names())
        assert DOMAIN_TABLES <= table_names
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                == "20260817_0001"
            )
    finally:
        engine.dispose()
        _validated_alembic_test_database_url(config)
        command.downgrade(config, "base")


def test_domain_metadata_declares_all_entity_tables_and_source_fields() -> None:
    from infra.postgres.models import Base

    assert set(Base.metadata.tables) == DOMAIN_TABLES
    for table in Base.metadata.tables.values():
        assert {"id", "source_system", "source_id", "source_updated_at"} <= {
            column.name for column in table.columns
        }
        assert table.c.id.primary_key
        assert not table.c.source_system.nullable
        assert not table.c.source_id.nullable
        assert not table.c.source_updated_at.nullable
        assert isinstance(table.c.source_updated_at.type, DateTime)
        assert table.c.source_updated_at.type.timezone is True
        assert any(
            isinstance(constraint, UniqueConstraint)
            and {column.name for column in constraint.columns}
            == {"source_system", "source_id"}
            for constraint in table.constraints
        )


def test_domain_metadata_matches_documented_foreign_keys() -> None:
    from infra.postgres.models import Base

    expected = {
        "ship_systems": {"ship_id": "ships.id"},
        "drawings": {"ship_id": "ships.id", "system_id": "ship_systems.id"},
        "equipment": {
            "ship_id": "ships.id",
            "system_id": "ship_systems.id",
            "drawing_id": "drawings.id",
        },
        "bom_items": {
            "drawing_id": "drawings.id",
            "equipment_id": "equipment.id",
            "material_id": "materials.id",
        },
        "purchase_orders": {
            "ship_id": "ships.id",
            "material_id": "materials.id",
            "equipment_id": "equipment.id",
            "supplier_id": "suppliers.id",
        },
        "project_tasks": {"ship_id": "ships.id"},
    }

    for table_name, expected_targets in expected.items():
        table = Base.metadata.tables[table_name]
        actual_targets = {
            column.name: next(iter(column.foreign_keys)).target_fullname
            for column in table.columns
            if column.foreign_keys
        }
        assert actual_targets == expected_targets


def test_domain_metadata_names_every_database_check() -> None:
    from infra.postgres.models import Base

    required_checks = {
        "bom_items": {"ck_bom_items_target", "ck_bom_items_quantity"},
        "project_tasks": {
            "ck_project_tasks_planned_dates",
            "ck_project_tasks_actual_dates",
            "ck_project_tasks_planned_progress",
            "ck_project_tasks_actual_progress",
        },
        "purchase_orders": {
            "ck_purchase_orders_target",
            "ck_purchase_orders_quantity",
        },
    }

    for table_name, names in required_checks.items():
        table = Base.metadata.tables[table_name]
        actual = {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert names <= actual
