from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TypedDict
from uuid import UUID

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
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.orm import Session

from packages.domain import (
    BOMItem,
    Drawing,
    Equipment,
    Material,
    PositiveQuantity,
    Progress,
    ProjectTask,
    PurchaseOrder,
    Ship,
    ShipSystem,
    Supplier,
)

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


class _SourceFields(TypedDict):
    id: UUID
    source_system: str
    source_id: str
    source_updated_at: datetime


SOURCE_UPDATED_AT = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)
SHIP_ID = UUID("10000000-0000-0000-0000-000000000001")
SYSTEM_ID = UUID("10000000-0000-0000-0000-000000000002")
DRAWING_ID = UUID("10000000-0000-0000-0000-000000000003")
EQUIPMENT_ID = UUID("10000000-0000-0000-0000-000000000004")
MATERIAL_ID = UUID("10000000-0000-0000-0000-000000000005")
SUPPLIER_ID = UUID("10000000-0000-0000-0000-000000000006")
BOM_ITEM_ID = UUID("10000000-0000-0000-0000-000000000007")
PURCHASE_ORDER_ID = UUID("10000000-0000-0000-0000-000000000008")
PROJECT_TASK_ID = UUID("10000000-0000-0000-0000-000000000009")


def _source_fields(entity_id: UUID, source_id: str) -> _SourceFields:
    return {
        "id": entity_id,
        "source_system": "synthetic-source",
        "source_id": source_id,
        "source_updated_at": SOURCE_UPDATED_AT,
    }


def _synthetic_domain_graph() -> tuple[
    Ship,
    ShipSystem,
    Drawing,
    Equipment,
    Material,
    Supplier,
    BOMItem,
    PurchaseOrder,
    ProjectTask,
]:
    ship = Ship(
        **_source_fields(SHIP_ID, "ship-001"),
        ship_code="SHIP-001",
        name="Synthetic Vessel",
        customer_name="Synthetic Customer",
        vessel_type="Research Vessel",
        planned_delivery_date=date(2027, 6, 1),
    )
    system = ShipSystem(
        **_source_fields(SYSTEM_ID, "system-001"),
        ship_id=ship.id,
        system_code="SYS-BALLAST",
        name="Ballast System",
    )
    drawing = Drawing(
        **_source_fields(DRAWING_ID, "drawing-001"),
        ship_id=ship.id,
        system_id=system.id,
        drawing_no="DWG-001",
        title="Synthetic Ballast Arrangement",
        revision="A",
        status="RELEASED",
    )
    equipment = Equipment(
        **_source_fields(EQUIPMENT_ID, "equipment-001"),
        ship_id=ship.id,
        system_id=system.id,
        drawing_id=drawing.id,
        equipment_code="EQ-PUMP-001",
        manufacturer="Synthetic Manufacturer",
        model="P-100",
    )
    material = Material(
        **_source_fields(MATERIAL_ID, "material-001"),
        material_code="MAT-001",
        description="Synthetic pipe section",
        specification="DN100",
        unit="m",
    )
    supplier = Supplier(
        **_source_fields(SUPPLIER_ID, "supplier-001"),
        supplier_code="SUP-001",
        canonical_name="Synthetic Supplier",
    )
    bom_item = BOMItem(
        **_source_fields(BOM_ITEM_ID, "bom-001"),
        drawing_id=drawing.id,
        equipment_id=equipment.id,
        material_id=material.id,
        quantity=PositiveQuantity(Decimal("12.5000")),
    )
    purchase_order = PurchaseOrder(
        **_source_fields(PURCHASE_ORDER_ID, "po-001"),
        ship_id=ship.id,
        material_id=material.id,
        equipment_id=equipment.id,
        supplier_id=supplier.id,
        po_number="PO-001",
        quantity=PositiveQuantity(Decimal("20.125000")),
        required_date=date(2027, 3, 1),
        promised_date=date(2027, 2, 15),
        actual_date=date(2027, 1, 20),
        status="DELIVERED",
        criticality="HIGH",
    )
    project_task = ProjectTask(
        **_source_fields(PROJECT_TASK_ID, "task-001"),
        ship_id=ship.id,
        task_code="TASK-001",
        name="Synthetic installation",
        planned_start=date(2027, 1, 1),
        planned_end=date(2027, 1, 31),
        actual_start=date(2027, 1, 2),
        actual_end=date(2027, 2, 2),
        planned_progress=Progress(Decimal("0.750000")),
        actual_progress=Progress(Decimal("0.625000")),
        critical_path=True,
    )
    return (
        ship,
        system,
        drawing,
        equipment,
        material,
        supplier,
        bom_item,
        purchase_order,
        project_task,
    )


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


@pytest.fixture()
def migrated_engine() -> Iterator[Engine]:
    url = _configured_test_database_url()
    config = _alembic_config(url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(config, "base")


@pytest.fixture()
def migrated_session(migrated_engine: Engine) -> Iterator[Session]:
    with Session(migrated_engine) as session:
        yield session


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


def test_repository_round_trips_complete_synthetic_domain_graph(
    migrated_session: Session,
) -> None:
    from infra.postgres.repositories import DomainRepository

    repository = DomainRepository(migrated_session)
    entities = _synthetic_domain_graph()
    for entity in entities:
        repository.insert(entity)
    migrated_session.commit()
    migrated_session.expunge_all()

    assert repository.get(Ship, SHIP_ID) == entities[0]
    assert repository.get(ShipSystem, SYSTEM_ID) == entities[1]
    assert repository.get(Drawing, DRAWING_ID) == entities[2]
    assert repository.get(Equipment, EQUIPMENT_ID) == entities[3]
    assert repository.get(Material, MATERIAL_ID) == entities[4]
    assert repository.get(Supplier, SUPPLIER_ID) == entities[5]
    assert repository.get(BOMItem, BOM_ITEM_ID) == entities[6]
    assert repository.get(PurchaseOrder, PURCHASE_ORDER_ID) == entities[7]
    assert repository.get(ProjectTask, PROJECT_TASK_ID) == entities[8]

    loaded_po = repository.get(PurchaseOrder, PURCHASE_ORDER_ID)
    assert loaded_po is not None
    assert loaded_po.actual_date is not None
    assert loaded_po.promised_date is not None
    assert loaded_po.required_date is not None
    assert loaded_po.actual_date < loaded_po.promised_date < loaded_po.required_date
    assert loaded_po.quantity == PositiveQuantity(Decimal("20.125000"))
    assert loaded_po.id != loaded_po.source_id


def test_repository_get_returns_none_for_missing_canonical_id(
    migrated_session: Session,
) -> None:
    from infra.postgres.repositories import DomainRepository

    repository = DomainRepository(migrated_session)

    assert repository.get(Ship, UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")) is None
