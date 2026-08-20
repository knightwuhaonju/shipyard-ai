from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, TypedDict, cast
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
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
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
from tests.integration.postgres_support import (
    alembic_config,
    configured_test_database_url,
    downgrade_to_base,
    validated_alembic_test_database_url,
    validated_test_database_url,
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


def test_test_database_url_rejects_non_test_database_without_leaking_secret() -> None:
    secret = "do-not-print"
    raw_url = f"postgresql+psycopg://shipyard:{secret}@localhost/shipyard_ai"

    with pytest.raises(ValueError) as captured:
        validated_test_database_url(raw_url)

    assert str(captured.value) == (
        "TEST_DATABASE_URL must name a database ending in _test"
    )
    assert secret not in str(captured.value)


def test_explicit_alembic_test_url_takes_precedence_over_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = configured_test_database_url()
    config = alembic_config(url)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+missingdriver://invalid:invalid@127.0.0.1/shipyard_ai",
    )

    command.current(config)

    assert validated_alembic_test_database_url(config) == url


def test_alembic_downgrade_rejects_other_test_database_before_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = alembic_config(
        make_url("postgresql+psycopg://shipyard:do-not-print@localhost/other_test")
    )
    downgrade_calls: list[tuple[Config, str]] = []

    def record_downgrade(config: Config, revision: str) -> None:
        downgrade_calls.append((config, revision))

    monkeypatch.setattr(command, "downgrade", record_downgrade)

    with pytest.raises(ValueError) as captured:
        downgrade_to_base(config)

    assert str(captured.value) == "Alembic must target database shipyard_ai_test"
    assert "do-not-print" not in str(captured.value)
    assert downgrade_calls == []


def test_migration_upgrades_an_empty_postgresql_database() -> None:
    url = configured_test_database_url()
    config = alembic_config(url)
    engine = create_engine(url)
    try:
        downgrade_to_base(config)
        assert DOMAIN_TABLES.isdisjoint(inspect(engine).get_table_names())

        command.upgrade(config, "head")

        table_names = set(inspect(engine).get_table_names())
        assert DOMAIN_TABLES <= table_names
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                == "20260820_0005"
            )
    finally:
        engine.dispose()
        downgrade_to_base(config)


def test_domain_metadata_declares_all_entity_tables_and_source_fields() -> None:
    from infra.postgres.models import Base

    assert DOMAIN_TABLES <= set(Base.metadata.tables)
    for table_name in DOMAIN_TABLES:
        table = Base.metadata.tables[table_name]
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


def test_repository_translates_duplicate_source_identity_without_value_leak(
    migrated_session: Session,
) -> None:
    from infra.postgres.repositories import (
        DomainPersistenceError,
        DomainRepository,
    )

    repository = DomainRepository(migrated_session)
    first = _synthetic_domain_graph()[0]
    repository.insert(first)
    migrated_session.commit()

    sensitive_source_id = first.source_id
    duplicate = Ship(
        **_source_fields(
            UUID("20000000-0000-0000-0000-000000000001"),
            sensitive_source_id,
        ),
        ship_code="SHIP-002",
    )

    with pytest.raises(DomainPersistenceError) as captured:
        repository.insert(duplicate)

    assert str(captured.value) == "domain entity violates persistence constraints"
    assert sensitive_source_id not in str(captured.value)
    assert repository.get(Ship, first.id) == first


def test_repository_translates_foreign_key_failure_and_preserves_session(
    migrated_session: Session,
) -> None:
    from infra.postgres.repositories import (
        DomainPersistenceError,
        DomainRepository,
    )

    repository = DomainRepository(migrated_session)
    invalid_system = ShipSystem(
        **_source_fields(
            UUID("20000000-0000-0000-0000-000000000002"),
            "missing-ship-system",
        ),
        ship_id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        system_code="SYS-MISSING",
        name="Synthetic missing system",
    )

    with pytest.raises(
        DomainPersistenceError,
        match="^domain entity violates persistence constraints$",
    ):
        repository.insert(invalid_system)

    valid_ship = _synthetic_domain_graph()[0]
    repository.insert(valid_ship)
    assert repository.get(Ship, valid_ship.id) == valid_ship


def test_repository_rejects_types_outside_task_005(migrated_session: Session) -> None:
    from infra.postgres.repositories import (
        DomainRepository,
        UnsupportedDomainEntityError,
    )

    repository = DomainRepository(migrated_session)

    with pytest.raises(
        UnsupportedDomainEntityError,
        match="^unsupported domain entity type$",
    ):
        repository.insert(cast(Any, object()))
    with pytest.raises(
        UnsupportedDomainEntityError,
        match="^unsupported domain entity type$",
    ):
        repository.get(cast(Any, str), SHIP_ID)


def _invalid_persistence_model(case: str) -> object:
    from infra.postgres.models import (
        BOMItemModel,
        MaterialModel,
        ProjectTaskModel,
        PurchaseOrderModel,
        ShipModel,
    )

    entity_id = UUID(
        {
            "blank_source": "30000000-0000-0000-0000-000000000001",
            "blank_text": "30000000-0000-0000-0000-000000000002",
            "bom_target": "30000000-0000-0000-0000-000000000003",
            "bom_zero": "30000000-0000-0000-0000-000000000004",
            "bom_nan": "30000000-0000-0000-0000-000000000005",
            "po_target": "30000000-0000-0000-0000-000000000006",
            "po_blank_optional": "30000000-0000-0000-0000-000000000007",
            "task_dates": "30000000-0000-0000-0000-000000000008",
            "task_progress": "30000000-0000-0000-0000-000000000009",
            "task_nan": "30000000-0000-0000-0000-000000000010",
        }[case]
    )
    source = _source_fields(entity_id, f"invalid-{case}")
    if case == "blank_source":
        return ShipModel(
            id=entity_id,
            source_system=" ",
            source_id=source["source_id"],
            source_updated_at=SOURCE_UPDATED_AT,
            ship_code="SHIP-INVALID-SOURCE",
        )
    if case == "blank_text":
        return MaterialModel(
            **source,
            material_code="MAT-INVALID-TEXT",
            description=" ",
        )
    if case == "bom_target":
        return BOMItemModel(
            **source,
            drawing_id=None,
            equipment_id=None,
            material_id=MATERIAL_ID,
            quantity=Decimal("1"),
        )
    if case == "bom_zero":
        return BOMItemModel(
            **source,
            drawing_id=DRAWING_ID,
            equipment_id=None,
            material_id=MATERIAL_ID,
            quantity=Decimal("0"),
        )
    if case == "bom_nan":
        return BOMItemModel(
            **source,
            drawing_id=DRAWING_ID,
            equipment_id=None,
            material_id=MATERIAL_ID,
            quantity=Decimal("NaN"),
        )
    if case == "po_target":
        return PurchaseOrderModel(
            **source,
            ship_id=SHIP_ID,
            material_id=None,
            equipment_id=None,
            supplier_id=SUPPLIER_ID,
            po_number="PO-INVALID-TARGET",
            status="OPEN",
        )
    if case == "po_blank_optional":
        return PurchaseOrderModel(
            **source,
            ship_id=SHIP_ID,
            material_id=MATERIAL_ID,
            equipment_id=None,
            supplier_id=SUPPLIER_ID,
            po_number="PO-INVALID-TEXT",
            status="OPEN",
            criticality=" ",
        )
    if case == "task_dates":
        return ProjectTaskModel(
            **source,
            ship_id=SHIP_ID,
            task_code="TASK-INVALID-DATES",
            name="Invalid date range",
            planned_start=date(2027, 2, 1),
            planned_end=date(2027, 1, 1),
        )
    if case == "task_progress":
        return ProjectTaskModel(
            **source,
            ship_id=SHIP_ID,
            task_code="TASK-INVALID-PROGRESS",
            name="Invalid progress",
            planned_progress=Decimal("1.1"),
        )
    if case == "task_nan":
        return ProjectTaskModel(
            **source,
            ship_id=SHIP_ID,
            task_code="TASK-NAN-PROGRESS",
            name="NaN progress",
            actual_progress=Decimal("NaN"),
        )
    raise AssertionError("unhandled constraint case")


@pytest.mark.parametrize(
    "case",
    [
        "blank_source",
        "blank_text",
        "bom_target",
        "bom_zero",
        "bom_nan",
        "po_target",
        "po_blank_optional",
        "task_dates",
        "task_progress",
        "task_nan",
    ],
)
def test_postgresql_rejects_domain_constraint_violations(
    migrated_session: Session,
    case: str,
) -> None:
    from infra.postgres.repositories import DomainRepository

    repository = DomainRepository(migrated_session)
    for entity in _synthetic_domain_graph()[:6]:
        repository.insert(entity)
    migrated_session.commit()

    with pytest.raises(IntegrityError):
        with migrated_session.begin_nested():
            migrated_session.add(_invalid_persistence_model(case))
            migrated_session.flush()
