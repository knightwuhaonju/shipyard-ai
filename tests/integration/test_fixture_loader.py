from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import literal, select
from sqlalchemy.orm import Session

from infra.postgres.alias_repository import AliasPersistenceError, AliasRepository
from infra.postgres.repositories import DomainPersistenceError, DomainRepository
from packages.contracts.auth import SecurityLevel
from packages.domain import (
    AliasEntityType,
    BOMItem,
    Drawing,
    EntityAlias,
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
from services.entity_resolution import EntityResolutionService
from tests.fixtures import (
    FixtureValidationError,
    load_shipyard_fixture_set,
    persist_shipyard_fixture_set,
)

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "shipyard"
ENTITY_FILES = {
    "ships.json": 2,
    "ship_systems.json": 2,
    "drawings.json": 2,
    "equipment.json": 2,
    "materials.json": 2,
    "bom_items.json": 2,
    "suppliers.json": 2,
    "purchase_orders.json": 4,
    "project_tasks.json": 4,
    "aliases.json": 5,
    "security_scopes.json": 2,
}
ALPHA_SHIP_ID = UUID("80000000-0000-0000-0000-000000000001")


def _json(name: str) -> Any:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _mutated_copy(
    tmp_path: Path,
    file_name: str,
    mutate: Callable[[Any], None],
) -> Path:
    root = tmp_path / "shipyard"
    shutil.copytree(FIXTURE_ROOT, root)
    value = json.loads((root / file_name).read_text(encoding="utf-8"))
    mutate(value)
    (root / file_name).write_text(
        json.dumps(value, ensure_ascii=False), encoding="utf-8"
    )
    return root


def test_checked_in_dataset_has_stable_synthetic_manifest_and_counts() -> None:
    manifest = _json("manifest.json")
    assert manifest == {
        "dataset_id": "synthetic-shipyard-v1",
        "dataset_version": 1,
        "synthetic": True,
        "as_of_date": "2026-08-18",
        "purchase_order_cases": {
            "overdue_ids": ["80000000-0000-0000-0000-000000000071"],
            "non_overdue_ids": [
                "80000000-0000-0000-0000-000000000073",
                "80000000-0000-0000-0000-000000000074",
            ],
            "delivered_ids": ["80000000-0000-0000-0000-000000000072"],
        },
        "security_scope_ships": {
            "ship-alpha-only": "80000000-0000-0000-0000-000000000001",
            "ship-beta-only": "80000000-0000-0000-0000-000000000002",
        },
    }
    assert {name: len(_json(name)) for name in ENTITY_FILES} == ENTITY_FILES


def test_loader_returns_deterministic_immutable_typed_graph() -> None:
    first = load_shipyard_fixture_set()
    second = load_shipyard_fixture_set()
    assert first == second
    assert first.dataset_id == "synthetic-shipyard-v1"
    assert first.dataset_version == 1
    assert first.as_of_date == date(2026, 8, 18)
    assert tuple(
        map(
            len,
            (
                first.ships,
                first.ship_systems,
                first.drawings,
                first.equipment,
                first.materials,
                first.bom_items,
                first.suppliers,
                first.purchase_orders,
                first.project_tasks,
                first.aliases,
                first.security_contexts,
            ),
        )
    ) == (2, 2, 2, 2, 2, 2, 2, 4, 4, 5, 2)
    assert first.bom_items[0].quantity == PositiveQuantity(Decimal("12.500"))
    assert first.project_tasks[0].planned_progress == Progress(Decimal("0.900"))
    assert (
        first.security_contexts[0].user_context.security_clearance
        is SecurityLevel.INTERNAL
    )
    with pytest.raises(FrozenInstanceError):
        first.dataset_version = 2  # type: ignore[misc]


def test_loader_preserves_provenance_relationships_cases_and_scope_mapping() -> None:
    fixtures = load_shipyard_fixture_set()
    sourced_groups = (
        fixtures.ships,
        fixtures.ship_systems,
        fixtures.drawings,
        fixtures.equipment,
        fixtures.materials,
        fixtures.bom_items,
        fixtures.suppliers,
        fixtures.purchase_orders,
        fixtures.project_tasks,
    )
    for record in (item for group in sourced_groups for item in group):
        assert record.source_system == "synthetic-fixture"
        assert record.source_id.startswith("synthetic:")
        assert record.source_updated_at.tzinfo is not None
        assert record.source_updated_at.utcoffset() == UTC.utcoffset(None)
        assert str(record.id) != record.source_id

    ship_ids = {ship.id for ship in fixtures.ships}
    assert {system.ship_id for system in fixtures.ship_systems} == ship_ids
    assert {drawing.ship_id for drawing in fixtures.drawings} == ship_ids
    assert {equipment.ship_id for equipment in fixtures.equipment} == ship_ids
    assert {order.ship_id for order in fixtures.purchase_orders} == ship_ids
    assert {task.ship_id for task in fixtures.project_tasks} == ship_ids
    assert fixtures.purchase_order_cases.overdue_ids == {
        UUID("80000000-0000-0000-0000-000000000071")
    }
    assert fixtures.purchase_order_cases.non_overdue_ids == {
        UUID("80000000-0000-0000-0000-000000000073"),
        UUID("80000000-0000-0000-0000-000000000074"),
    }
    contexts = {item.name: item.user_context for item in fixtures.security_contexts}
    assert contexts["ship-alpha-only"].allowed_ship_ids == {
        "80000000-0000-0000-0000-000000000001"
    }
    assert contexts["ship-beta-only"].allowed_ship_ids == {
        "80000000-0000-0000-0000-000000000002"
    }


@pytest.mark.parametrize(
    ("file_name", "mutate", "category"),
    [
        (
            "manifest.json",
            lambda value: value.update(synthetic=False),
            "manifest",
        ),
        (
            "ships.json",
            lambda value: value[0].update(
                source_system="RAW-MUTATED-SENTINEL"
            ),
            "provenance",
        ),
        (
            "ships.json",
            lambda value: value[0].update(unexpected=True),
            "schema",
        ),
        (
            "ships.json",
            lambda value: value[0].pop("ship_code"),
            "schema",
        ),
        (
            "ships.json",
            lambda value: value[1].update(id=value[0]["id"]),
            "duplicate id",
        ),
        (
            "ships.json",
            lambda value: value[1].update(source_id=value[0]["source_id"]),
            "duplicate source",
        ),
        (
            "bom_items.json",
            lambda value: value[0].update(quantity=12.5),
            "schema",
        ),
        (
            "project_tasks.json",
            lambda value: value[0].update(planned_progress=0.9),
            "schema",
        ),
        (
            "manifest.json",
            lambda value: value.update(dataset_version=True),
            "manifest",
        ),
        (
            "manifest.json",
            lambda value: value.update(as_of_date="20260818"),
            "manifest",
        ),
        (
            "ships.json",
            lambda value: value[0].update(
                planned_delivery_date="20270630"
            ),
            "schema",
        ),
        (
            "ships.json",
            lambda value: value[0].update(
                source_updated_at="2026-08-18T00:00:00"
            ),
            "schema",
        ),
        (
            "ship_systems.json",
            lambda value: value[0].update(
                ship_id="80000000-0000-0000-0000-000000000099"
            ),
            "relationship",
        ),
        (
            "drawings.json",
            lambda value: value[0].update(
                system_id="80000000-0000-0000-0000-000000000012"
            ),
            "relationship",
        ),
        (
            "equipment.json",
            lambda value: value[0].update(
                ship_id="80000000-0000-0000-0000-000000000002"
            ),
            "relationship",
        ),
        (
            "bom_items.json",
            lambda value: value[0].update(
                drawing_id="80000000-0000-0000-0000-000000000022"
            ),
            "relationship",
        ),
        (
            "purchase_orders.json",
            lambda value: value[0].update(
                ship_id="80000000-0000-0000-0000-000000000002"
            ),
            "relationship",
        ),
        (
            "project_tasks.json",
            lambda value: value[0].update(
                ship_id="80000000-0000-0000-0000-000000000099"
            ),
            "relationship",
        ),
        (
            "aliases.json",
            lambda value: value[0].update(
                entity_id="80000000-0000-0000-0000-000000000099"
            ),
            "relationship",
        ),
        (
            "manifest.json",
            lambda value: value["purchase_order_cases"].update(
                overdue_ids=["80000000-0000-0000-0000-000000000073"]
            ),
            "purchase-order case",
        ),
        (
            "security_scopes.json",
            lambda value: value[0].update(
                allowed_ship_ids=[
                    "80000000-0000-0000-0000-000000000002"
                ]
            ),
            "security scope",
        ),
    ],
)
def test_loader_rejects_invalid_dataset_without_leaking_values(
    tmp_path: Path,
    file_name: str,
    mutate: Callable[[Any], None],
    category: str,
) -> None:
    root = _mutated_copy(tmp_path, file_name, mutate)
    with pytest.raises(FixtureValidationError) as captured:
        load_shipyard_fixture_set(root)
    message = str(captured.value)
    assert re.fullmatch(
        rf"{re.escape(file_name)}(?::\d+)?: {re.escape(category)}",
        message,
    )


def test_loader_rejects_invalid_json_without_leaking_root(tmp_path: Path) -> None:
    root = _mutated_copy(tmp_path, "ships.json", lambda value: None)
    (root / "ships.json").write_text("{", encoding="utf-8")

    with pytest.raises(FixtureValidationError) as captured:
        load_shipyard_fixture_set(root)

    assert str(captured.value) == "ships.json: invalid JSON"
    assert str(root) not in str(captured.value)


def test_loader_rejects_invalid_utf8_without_leaking_root(tmp_path: Path) -> None:
    root = _mutated_copy(tmp_path, "ships.json", lambda value: None)
    (root / "ships.json").write_bytes(b"\xffRAW-MUTATED-SENTINEL")

    with pytest.raises(FixtureValidationError) as captured:
        load_shipyard_fixture_set(root)

    assert str(captured.value) == "ships.json: invalid encoding"


def test_persisted_fixture_graph_round_trips_through_public_repositories(
    migrated_session: Session,
) -> None:
    fixtures = load_shipyard_fixture_set()
    persist_shipyard_fixture_set(migrated_session, fixtures)
    repository = DomainRepository(migrated_session)
    for ship in fixtures.ships:
        assert repository.get(Ship, ship.id) == ship
    for system in fixtures.ship_systems:
        assert repository.get(ShipSystem, system.id) == system
    for drawing in fixtures.drawings:
        assert repository.get(Drawing, drawing.id) == drawing
    for equipment in fixtures.equipment:
        assert repository.get(Equipment, equipment.id) == equipment
    for material in fixtures.materials:
        assert repository.get(Material, material.id) == material
    for supplier in fixtures.suppliers:
        assert repository.get(Supplier, supplier.id) == supplier
    for bom_item in fixtures.bom_items:
        assert repository.get(BOMItem, bom_item.id) == bom_item
    for purchase_order in fixtures.purchase_orders:
        assert repository.get(PurchaseOrder, purchase_order.id) == purchase_order
    for project_task in fixtures.project_tasks:
        assert repository.get(ProjectTask, project_task.id) == project_task
    aliases = AliasRepository(migrated_session)
    for alias in fixtures.aliases:
        assert aliases.resolve(alias.entity_type, alias.alias) == alias


def test_persistence_leaves_commit_and_rollback_to_caller(
    migrated_session: Session,
) -> None:
    persist_shipyard_fixture_set(migrated_session, load_shipyard_fixture_set())
    assert DomainRepository(migrated_session).get(Ship, ALPHA_SHIP_ID) is not None
    migrated_session.rollback()
    assert DomainRepository(migrated_session).get(Ship, ALPHA_SHIP_ID) is None


def test_persistence_revalidates_manual_fixture_before_writing(
    migrated_session: Session,
) -> None:
    fixtures = load_shipyard_fixture_set()
    cross_ship_equipment = replace(
        fixtures.equipment[0],
        ship_id=fixtures.ships[1].id,
    )
    invalid = replace(
        fixtures,
        equipment=(cross_ship_equipment, *fixtures.equipment[1:]),
    )

    with pytest.raises(
        FixtureValidationError,
        match=r"^equipment\.json:0: relationship$",
    ):
        persist_shipyard_fixture_set(migrated_session, invalid)

    assert not migrated_session.in_transaction()
    assert DomainRepository(migrated_session).get(Ship, ALPHA_SHIP_ID) is None
    assert migrated_session.scalar(select(literal(1))) == 1


def test_duplicate_persistence_fails_without_overwriting_first_dataset(
    migrated_session: Session,
) -> None:
    fixtures = load_shipyard_fixture_set()
    persist_shipyard_fixture_set(migrated_session, fixtures)
    with pytest.raises(DomainPersistenceError):
        persist_shipyard_fixture_set(migrated_session, fixtures)
    assert (
        DomainRepository(migrated_session).get(Ship, ALPHA_SHIP_ID)
        == fixtures.ships[0]
    )


def test_alias_failure_rolls_back_whole_dataset_and_session_remains_usable(
    migrated_session: Session,
) -> None:
    fixtures = load_shipyard_fixture_set()
    collision = EntityAlias(
        id=UUID("80000000-0000-0000-0000-000000000096"),
        entity_type=AliasEntityType.EQUIPMENT,
        entity_id=fixtures.equipment[0].id,
        alias="  SYNTHETIC   ALPHA MAIN COOLING PUMP  ",
    )
    invalid = replace(fixtures, aliases=(*fixtures.aliases, collision))
    with pytest.raises(AliasPersistenceError):
        persist_shipyard_fixture_set(migrated_session, invalid)
    assert DomainRepository(migrated_session).get(Ship, ALPHA_SHIP_ID) is None
    assert migrated_session.scalar(select(literal(1))) == 1


def test_fixture_equipment_aliases_respect_both_ship_security_scopes(
    migrated_session: Session,
) -> None:
    fixtures = load_shipyard_fixture_set()
    persist_shipyard_fixture_set(migrated_session, fixtures)
    domain_repository = DomainRepository(migrated_session)
    service = EntityResolutionService(
        AliasRepository(migrated_session),
        lambda entity_id: domain_repository.get(Equipment, entity_id),
    )
    contexts = {item.name: item.user_context for item in fixtures.security_contexts}
    alpha_alias = "Synthetic Alpha Main Cooling Pump"
    beta_alias = "Synthetic Beta Main Generator"

    alpha_result = service.resolve(
        entity_type=AliasEntityType.EQUIPMENT,
        raw_alias=alpha_alias,
        user_context=contexts["ship-alpha-only"],
    )
    assert alpha_result is not None
    assert alpha_result.entity_id == UUID("80000000-0000-0000-0000-000000000031")
    assert service.resolve(
        entity_type=AliasEntityType.EQUIPMENT,
        raw_alias=beta_alias,
        user_context=contexts["ship-alpha-only"],
    ) is None

    beta_result = service.resolve(
        entity_type=AliasEntityType.EQUIPMENT,
        raw_alias=beta_alias,
        user_context=contexts["ship-beta-only"],
    )
    assert beta_result is not None
    assert beta_result.entity_id == UUID("80000000-0000-0000-0000-000000000032")
    assert service.resolve(
        entity_type=AliasEntityType.EQUIPMENT,
        raw_alias=alpha_alias,
        user_context=contexts["ship-beta-only"],
    ) is None
    assert service.resolve(
        entity_type=AliasEntityType.EQUIPMENT,
        raw_alias="Synthetic Alpha Main Cooling Pumps",
        user_context=contexts["ship-alpha-only"],
    ) is None


def test_fixture_supplier_aliases_are_explicit_and_exact(
    migrated_session: Session,
) -> None:
    fixtures = load_shipyard_fixture_set()
    persist_shipyard_fixture_set(migrated_session, fixtures)
    repository = AliasRepository(migrated_session)
    expected_id = UUID("80000000-0000-0000-0000-000000000051")
    for raw_alias in (
        "Synthetic Northstar Marine Systems",
        "SNMS",
        "合成北星船舶系统",
    ):
        resolved = repository.resolve(AliasEntityType.SUPPLIER, raw_alias)
        assert resolved is not None
        assert resolved.entity_id == expected_id
    assert repository.resolve(AliasEntityType.SUPPLIER, "Northstar") is None
