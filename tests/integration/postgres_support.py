"""Shared protected PostgreSQL integration-test operations."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL, make_url

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXPLICIT_DATABASE_URL_ATTRIBUTE = "shipyard_ai_explicit_database_url"


def validated_test_database_url(raw_url: str) -> URL:
    url = make_url(raw_url)
    if url.database is None or not url.database.endswith("_test"):
        raise ValueError("TEST_DATABASE_URL must name a database ending in _test")
    return url


def configured_test_database_url() -> URL:
    raw_url = os.getenv("TEST_DATABASE_URL")
    if raw_url is None:
        pytest.skip("TEST_DATABASE_URL is not configured")
    try:
        return validated_test_database_url(raw_url)
    except ValueError as exc:
        pytest.fail(str(exc), pytrace=False)


def alembic_config(url: URL) -> Config:
    config = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    rendered_url = url.render_as_string(hide_password=False).replace("%", "%%")
    config.set_main_option("sqlalchemy.url", rendered_url)
    config.attributes[EXPLICIT_DATABASE_URL_ATTRIBUTE] = True
    return config


def validated_alembic_test_database_url(config: Config) -> URL:
    raw_url = config.get_main_option("sqlalchemy.url")
    if raw_url is None:
        raise ValueError("Alembic must have an explicitly configured test database")
    url = validated_test_database_url(raw_url)
    if url.database != "shipyard_ai_test":
        raise ValueError("Alembic must target database shipyard_ai_test")
    return url


def downgrade_to_base(config: Config) -> None:
    validated_alembic_test_database_url(config)
    command.downgrade(config, "base")
