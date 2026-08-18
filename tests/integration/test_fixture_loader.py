from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from datetime import UTC, date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from packages.contracts.auth import SecurityLevel
from packages.domain import PositiveQuantity, Progress
from tests.fixtures import FixtureValidationError, load_shipyard_fixture_set

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
