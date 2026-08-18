from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.integration.postgres_support import (
    alembic_config,
    configured_test_database_url,
    downgrade_to_base,
)


@pytest.fixture()
def migrated_engine() -> Iterator[Engine]:
    url = configured_test_database_url()
    config = alembic_config(url)
    downgrade_to_base(config)
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()
        downgrade_to_base(config)


@pytest.fixture()
def migrated_session(migrated_engine: Engine) -> Iterator[Session]:
    with Session(migrated_engine) as session:
        yield session
