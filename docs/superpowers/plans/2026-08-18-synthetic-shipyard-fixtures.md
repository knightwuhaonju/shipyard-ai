# Synthetic Shipyard Fixtures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one deterministic, entirely synthetic, reusable two-ship fixture dataset with strict in-memory loading, repository-owned PostgreSQL persistence, aliases, and mutually isolated security contexts.

**Architecture:** All new runtime helpers remain test-only under `tests/fixtures`; they construct the existing immutable domain and authentication contracts and persist only through `DomainRepository` and `AliasRepository`. Validation occurs before persistence, uses the manifest's fixed date rather than wall-clock time, and the caller retains transaction ownership.

**Tech Stack:** Python 3.12, standard-library JSON/dataclasses/datetime/decimal/pathlib/UUID, SQLAlchemy 2.x `Session`, pytest, PostgreSQL 16, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-18-synthetic-shipyard-fixtures-design.md`

## Global Constraints

- Implement Task 008 only; do not start Task 009.
- Keep all fixture code and data under `tests/fixtures`; production packages must not import it.
- Use exactly `dataset_id = "synthetic-shipyard-v1"`, `dataset_version = 1`, `synthetic = true`, and `as_of_date = "2026-08-18"`.
- Every sourced record must use `source_system = "synthetic-fixture"`, a `source_id` beginning with `synthetic:`, and a timezone-aware `source_updated_at`.
- Canonical IDs are fixed UUIDs and must never equal or derive from source-system IDs.
- JSON UUIDs are canonical lowercase strings; dates and datetimes are ISO strings; quantities and progress are decimal strings, never JSON numbers.
- Use only fictional, visibly synthetic names. Do not copy real company, customer, vessel, supplier, PO, credential, or document data.
- Persist through public repositories only, inside one outer `Session.begin_nested()` savepoint; never commit, update, delete, truncate, call `create_all`, or upsert.
- Alias resolution remains explicit and exact. Authorization remains enforced by `EntityResolutionService` using trusted `UserContext` values.
- Each behavior slice must follow RED, focused GREEN, relevant suite, Ruff, and mypy before its commit.

## File Map

- Create `tests/fixtures/__init__.py`: re-export the six fixture-loader public names.
- Create `tests/fixtures/loader.py`: immutable result contracts, strict JSON parsing, graph/scenario validation, and repository persistence.
- Create `tests/fixtures/README.md`: synthetic-data contract, dataset layout, usage, transaction ownership, and protected database command.
- Create `tests/fixtures/shipyard/manifest.json`: stable dataset identity, fixed scenario IDs, and scope-to-ship mapping.
- Create eleven entity/context JSON files under `tests/fixtures/shipyard`: reviewable source data by canonical type.
- Create `tests/integration/test_fixture_loader.py`: raw-contract, loader, validation, persistence, rollback, alias, and authorization integration coverage.
- Do not modify production source or migrations.

---

### Task 1: Checked-in synthetic dataset contract

**Files:**
- Create: `tests/integration/test_fixture_loader.py`
- Create: `tests/fixtures/shipyard/manifest.json`
- Create: `tests/fixtures/shipyard/ships.json`
- Create: `tests/fixtures/shipyard/ship_systems.json`
- Create: `tests/fixtures/shipyard/drawings.json`
- Create: `tests/fixtures/shipyard/equipment.json`
- Create: `tests/fixtures/shipyard/materials.json`
- Create: `tests/fixtures/shipyard/bom_items.json`
- Create: `tests/fixtures/shipyard/suppliers.json`
- Create: `tests/fixtures/shipyard/purchase_orders.json`
- Create: `tests/fixtures/shipyard/project_tasks.json`
- Create: `tests/fixtures/shipyard/aliases.json`
- Create: `tests/fixtures/shipyard/security_scopes.json`

**Interfaces:**
- Consumes: the Task 005-007 domain field names and the approved design spec.
- Produces: stable JSON inputs later consumed by `load_shipyard_fixture_set()`.

- [ ] **Step 1: Write the failing raw-dataset contract test**

Create `tests/integration/test_fixture_loader.py` with these imports, constants, helper, and first test:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_fixture_loader.py::test_checked_in_dataset_has_stable_synthetic_manifest_and_counts -v
```

Expected: FAIL with `FileNotFoundError` for `tests/fixtures/shipyard/manifest.json`.

- [ ] **Step 3: Create the exact fixture records**

Use these fixed common source values on every sourced entity:

```json
{
  "source_system": "synthetic-fixture",
  "source_updated_at": "2026-08-18T00:00:00+00:00"
}
```

Create `manifest.json` with the exact mapping asserted in Step 1. Create the remaining files as JSON arrays using the following exact records; preserve the listed order and include every nullable field explicitly.

| File | UUID suffix | Required values beyond common source fields |
|---|---:|---|
| `ships.json` | 001 | `source_id="synthetic:ship:alpha"`, `ship_code="SYN-ALPHA"`, `name="Synthetic Vessel Alpha"`, `customer_name="Synthetic Customer Alpha"`, `vessel_type="Offshore Support Vessel"`, `planned_delivery_date="2027-06-30"` |
| `ships.json` | 002 | `source_id="synthetic:ship:beta"`, `ship_code="SYN-BETA"`, `name="Synthetic Vessel Beta"`, `customer_name="Synthetic Customer Beta"`, `vessel_type="Research Vessel"`, `planned_delivery_date="2027-12-15"` |
| `ship_systems.json` | 011 | Alpha ship, `source_id="synthetic:system:alpha-cooling"`, `system_code="SYS-ALPHA-COOL"`, `name="Synthetic Alpha Cooling System"` |
| `ship_systems.json` | 012 | Beta ship, `source_id="synthetic:system:beta-electrical"`, `system_code="SYS-BETA-ELEC"`, `name="Synthetic Beta Electrical System"` |
| `drawings.json` | 021 | Alpha ship/system, `source_id="synthetic:drawing:alpha-cooling"`, `drawing_no="SYN-DWG-A-001"`, `title="Synthetic Alpha Cooling Arrangement"`, `revision="A"`, `status="APPROVED"` |
| `drawings.json` | 022 | Beta ship/system, `source_id="synthetic:drawing:beta-electrical"`, `drawing_no="SYN-DWG-B-001"`, `title="Synthetic Beta Electrical Arrangement"`, `revision="B"`, `status="REVIEW"` |
| `equipment.json` | 031 | Alpha ship/system/drawing, `source_id="synthetic:equipment:alpha-pump"`, `equipment_code="SYN-EQ-A-PUMP"`, `manufacturer="Synthetic Northstar Marine Systems"`, `model="NS-P100"` |
| `equipment.json` | 032 | Beta ship/system/drawing, `source_id="synthetic:equipment:beta-generator"`, `equipment_code="SYN-EQ-B-GEN"`, `manufacturer="Synthetic Meridian Electric"`, `model="ME-G200"` |
| `materials.json` | 041 | `source_id="synthetic:material:pipe-dn100"`, `material_code="SYN-MAT-PIPE-100"`, `description="Synthetic DN100 cooling pipe"`, `specification="SYN-SPEC-DN100"`, `unit="m"` |
| `materials.json` | 042 | `source_id="synthetic:material:cable-power"`, `material_code="SYN-MAT-CABLE-200"`, `description="Synthetic marine power cable"`, `specification="SYN-SPEC-CABLE-200"`, `unit="m"` |
| `bom_items.json` | 061 | Alpha drawing/equipment/material, `source_id="synthetic:bom:alpha-pipe"`, `quantity="12.500"` |
| `bom_items.json` | 062 | Beta drawing/equipment/material, `source_id="synthetic:bom:beta-cable"`, `quantity="40.000"` |
| `suppliers.json` | 051 | `source_id="synthetic:supplier:northstar"`, `supplier_code="SYN-SUP-NORTHSTAR"`, `canonical_name="Synthetic Northstar Marine Systems"` |
| `suppliers.json` | 052 | `source_id="synthetic:supplier:meridian"`, `supplier_code="SYN-SUP-MERIDIAN"`, `canonical_name="Synthetic Meridian Electric"` |
| `purchase_orders.json` | 071 | Alpha/Northstar/equipment 031, material `null`, `source_id="synthetic:po:alpha-overdue"`, `po_number="SYN-PO-A-OVERDUE"`, `status="OPEN"`, `quantity="1.000"`, `required_date="2026-07-25"`, `promised_date="2026-08-01"`, `actual_date=null`, `criticality="HIGH"` |
| `purchase_orders.json` | 072 | Alpha/Northstar/material 041, equipment `null`, `source_id="synthetic:po:alpha-delivered"`, `po_number="SYN-PO-A-DELIVERED"`, `status="DELIVERED"`, `quantity="12.500"`, `required_date="2026-07-15"`, `promised_date="2026-07-12"`, `actual_date="2026-07-10"`, `criticality="MEDIUM"` |
| `purchase_orders.json` | 073 | Beta/Meridian/equipment 032, material `null`, `source_id="synthetic:po:beta-future"`, `po_number="SYN-PO-B-FUTURE"`, `status="OPEN"`, `quantity="1.000"`, `required_date="2026-09-20"`, `promised_date="2026-09-15"`, `actual_date=null`, `criticality="HIGH"` |
| `purchase_orders.json` | 074 | Beta/Meridian/material 042, equipment `null`, `source_id="synthetic:po:beta-boundary"`, `po_number="SYN-PO-B-BOUNDARY"`, `status="OPEN"`, `quantity="40.000"`, `required_date="2026-08-18"`, `promised_date="2026-08-18"`, `actual_date=null`, `criticality="LOW"` |
| `project_tasks.json` | 081 | Alpha ship, `source_id="synthetic:task:alpha-design"`, `task_code="SYN-A-DESIGN"`, `name="Synthetic Alpha Detail Design"`, dates `2026-07-01`, `2026-08-31`, `2026-07-01`, `null`, progress `"0.900"`, `"0.800"`, `critical_path=true` |
| `project_tasks.json` | 082 | Alpha ship, `source_id="synthetic:task:alpha-install"`, `task_code="SYN-A-INSTALL"`, `name="Synthetic Alpha Equipment Installation"`, dates `2026-09-01`, `2026-10-31`, `null`, `null`, progress `"0.100"`, `"0.000"`, `critical_path=false` |
| `project_tasks.json` | 083 | Beta ship, `source_id="synthetic:task:beta-design"`, `task_code="SYN-B-DESIGN"`, `name="Synthetic Beta Detail Design"`, dates `2026-08-01`, `2026-09-30`, `2026-08-01`, `null`, progress `"0.500"`, `"0.400"`, `critical_path=true` |
| `project_tasks.json` | 084 | Beta ship, `source_id="synthetic:task:beta-install"`, `task_code="SYN-B-INSTALL"`, `name="Synthetic Beta Equipment Installation"`, dates `2026-10-01`, `2026-11-30`, `null`, `null`, progress `"0.000"`, `"0.000"`, `critical_path=false` |

All IDs are `80000000-0000-0000-0000-000000000XYZ`, where `XYZ` is the three-digit suffix. Relationship fields use the corresponding full UUID. Project-task date columns, in order, are `planned_start`, `planned_end`, `actual_start`, `actual_end`; progress columns are `planned_progress`, `actual_progress`.

Create `aliases.json` exactly as:

```json
[
  {"id":"80000000-0000-0000-0000-000000000091","entity_type":"supplier","entity_id":"80000000-0000-0000-0000-000000000051","alias":"Synthetic Northstar Marine Systems","source_system":null},
  {"id":"80000000-0000-0000-0000-000000000092","entity_type":"supplier","entity_id":"80000000-0000-0000-0000-000000000051","alias":"SNMS","source_system":null},
  {"id":"80000000-0000-0000-0000-000000000093","entity_type":"supplier","entity_id":"80000000-0000-0000-0000-000000000051","alias":"合成北星船舶系统","source_system":null},
  {"id":"80000000-0000-0000-0000-000000000094","entity_type":"equipment","entity_id":"80000000-0000-0000-0000-000000000031","alias":"Synthetic Alpha Main Cooling Pump","source_system":null},
  {"id":"80000000-0000-0000-0000-000000000095","entity_type":"equipment","entity_id":"80000000-0000-0000-0000-000000000032","alias":"Synthetic Beta Main Generator","source_system":null}
]
```

Create `security_scopes.json` exactly as:

```json
[
  {"name":"ship-alpha-only","user_id":"synthetic-user-alpha","roles":[],"departments":[],"allowed_ship_ids":["80000000-0000-0000-0000-000000000001"],"allowed_project_ids":[],"security_clearance":"INTERNAL"},
  {"name":"ship-beta-only","user_id":"synthetic-user-beta","roles":[],"departments":[],"allowed_ship_ids":["80000000-0000-0000-0000-000000000002"],"allowed_project_ids":[],"security_clearance":"INTERNAL"}
]
```

- [ ] **Step 4: Run the raw contract test to verify GREEN**

Run the Step 2 command. Expected: `1 passed`.

- [ ] **Step 5: Commit the dataset slice**

```bash
git add tests/fixtures/shipyard tests/integration/test_fixture_loader.py
git commit -m "test: add deterministic synthetic shipyard dataset"
```

---

### Task 2: Immutable strict loader and semantic validation

**Files:**
- Create: `tests/fixtures/__init__.py`
- Create: `tests/fixtures/loader.py`
- Modify: `tests/integration/test_fixture_loader.py`

**Interfaces:**
- Consumes: the JSON contract from Task 1; existing `packages.domain` constructors; `packages.contracts.auth.UserContext` and `SecurityLevel`.
- Produces: `FixtureValidationError`, `PurchaseOrderCases`, `NamedUserContext`, `ShipyardFixtureSet`, and `load_shipyard_fixture_set(root: Path | None = None) -> ShipyardFixtureSet`.

- [ ] **Step 1: Write failing typed-load and determinism tests**

Append these imports and tests, keeping import ordering Ruff-compliant:

```python
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date
from decimal import Decimal
from uuid import UUID

import pytest

from packages.contracts.auth import SecurityLevel
from packages.domain import AliasEntityType, PositiveQuantity, Progress
from tests.fixtures import FixtureValidationError, load_shipyard_fixture_set


def test_loader_returns_deterministic_immutable_typed_graph() -> None:
    first = load_shipyard_fixture_set()
    second = load_shipyard_fixture_set()
    assert first == second
    assert first.dataset_id == "synthetic-shipyard-v1"
    assert first.dataset_version == 1
    assert first.as_of_date == date(2026, 8, 18)
    assert tuple(map(len, (
        first.ships, first.ship_systems, first.drawings, first.equipment,
        first.materials, first.bom_items, first.suppliers,
        first.purchase_orders, first.project_tasks, first.aliases,
        first.security_contexts,
    ))) == (2, 2, 2, 2, 2, 2, 2, 4, 4, 5, 2)
    assert first.bom_items[0].quantity == PositiveQuantity(Decimal("12.500"))
    assert first.project_tasks[0].planned_progress == Progress(Decimal("0.900"))
    assert first.security_contexts[0].user_context.security_clearance is SecurityLevel.INTERNAL
    with pytest.raises(FrozenInstanceError):
        first.dataset_version = 2  # type: ignore[misc]


def test_loader_preserves_provenance_relationships_cases_and_scope_mapping() -> None:
    fixtures = load_shipyard_fixture_set()
    sourced_groups = (
        fixtures.ships, fixtures.ship_systems, fixtures.drawings,
        fixtures.equipment, fixtures.materials, fixtures.bom_items,
        fixtures.suppliers, fixtures.purchase_orders, fixtures.project_tasks,
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
```

- [ ] **Step 2: Run the typed-load tests to verify RED**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_fixture_loader.py -k 'loader_returns or loader_preserves' -v
```

Expected: collection ERROR with `ModuleNotFoundError: No module named 'tests.fixtures'`.

- [ ] **Step 3: Add the public immutable contracts and strict loader**

Create `tests/fixtures/__init__.py` with only these re-exports:

```python
"""Reusable deterministic test fixtures."""

from tests.fixtures.loader import (
    FixtureValidationError,
    NamedUserContext,
    PurchaseOrderCases,
    ShipyardFixtureSet,
    load_shipyard_fixture_set,
    persist_shipyard_fixture_set,
)

__all__ = [
    "FixtureValidationError",
    "NamedUserContext",
    "PurchaseOrderCases",
    "ShipyardFixtureSet",
    "load_shipyard_fixture_set",
    "persist_shipyard_fixture_set",
]
```

In `tests/fixtures/loader.py`, define these exact public contracts:

```python
class FixtureValidationError(ValueError):
    """Raised when checked-in synthetic fixture data violates its contract."""


@dataclass(frozen=True, slots=True)
class PurchaseOrderCases:
    overdue_ids: frozenset[UUID]
    non_overdue_ids: frozenset[UUID]
    delivered_ids: frozenset[UUID]


@dataclass(frozen=True, slots=True)
class NamedUserContext:
    name: str
    user_context: UserContext


@dataclass(frozen=True, slots=True)
class ShipyardFixtureSet:
    dataset_id: str
    dataset_version: int
    as_of_date: date
    ships: tuple[Ship, ...]
    ship_systems: tuple[ShipSystem, ...]
    drawings: tuple[Drawing, ...]
    equipment: tuple[Equipment, ...]
    materials: tuple[Material, ...]
    bom_items: tuple[BOMItem, ...]
    suppliers: tuple[Supplier, ...]
    purchase_orders: tuple[PurchaseOrder, ...]
    project_tasks: tuple[ProjectTask, ...]
    aliases: tuple[EntityAlias, ...]
    security_contexts: tuple[NamedUserContext, ...]
    purchase_order_cases: PurchaseOrderCases
```

Use a private `_DEFAULT_ROOT = Path(__file__).parent / "shipyard"`, a fixed tuple of the 12 accepted file names, and `json.loads(path.read_text(encoding="utf-8"))`. Implement strict record helpers that:

1. require the top-level manifest to be a JSON object and every other file to be an array of objects;
2. compare `set(record)` to the exact required/optional field set and reject missing/unknown keys;
3. reject `bool` where an integer is required;
4. require canonical UUID text with `str(UUID(value)) == value`;
5. parse dates with `date.fromisoformat`, datetimes with `datetime.fromisoformat`, and require non-`None` UTC offset;
6. accept Decimal input only from a JSON string and construct `PositiveQuantity` or `Progress`;
7. wrap `JSONDecodeError`, `OSError`, `ValueError`, `TypeError`, `KeyError`, `DomainValidationError`, and Pydantic `ValidationError` in `FixtureValidationError` whose text is only `"<relative-file>[:<index>]: <fixed category>"`.

Define the trusted fixed scope baseline independently from parsed input so a
hand-constructed fixture set cannot redefine its own authorization invariant:

```python
_EXPECTED_SECURITY_SCOPE_SHIPS = {
    "ship-alpha-only": UUID("80000000-0000-0000-0000-000000000001"),
    "ship-beta-only": UUID("80000000-0000-0000-0000-000000000002"),
}
```

Construct every domain entity with keyword arguments matching its dataclass. Parse alias `entity_type` via `AliasEntityType(value)`, never accept `normalized_alias`, and construct each security record as:

```python
NamedUserContext(
    name=_text(record, "name"),
    user_context=UserContext(
        user_id=_text(record, "user_id"),
        roles=frozenset(_text_list(record, "roles")),
        departments=frozenset(_text_list(record, "departments")),
        allowed_ship_ids=frozenset(_uuid_text_list(record, "allowed_ship_ids")),
        allowed_project_ids=frozenset(
            _uuid_text_list(record, "allowed_project_ids")
        ),
        security_clearance=SecurityLevel[_text(record, "security_clearance")],
    ),
)
```

Implement `load_shipyard_fixture_set(root: Path | None = None)` in this order:

```python
def load_shipyard_fixture_set(root: Path | None = None) -> ShipyardFixtureSet:
    fixture_root = _DEFAULT_ROOT if root is None else root
    manifest = _load_object(fixture_root, "manifest.json")
    fixture_set = ShipyardFixtureSet(
        dataset_id=_manifest_dataset_id(manifest),
        dataset_version=_manifest_dataset_version(manifest),
        as_of_date=_manifest_as_of_date(manifest),
        ships=_load_entities(fixture_root, "ships.json", _ship),
        ship_systems=_load_entities(
            fixture_root, "ship_systems.json", _ship_system
        ),
        drawings=_load_entities(fixture_root, "drawings.json", _drawing),
        equipment=_load_entities(fixture_root, "equipment.json", _equipment),
        materials=_load_entities(fixture_root, "materials.json", _material),
        bom_items=_load_entities(fixture_root, "bom_items.json", _bom_item),
        suppliers=_load_entities(fixture_root, "suppliers.json", _supplier),
        purchase_orders=_load_entities(
            fixture_root, "purchase_orders.json", _purchase_order
        ),
        project_tasks=_load_entities(
            fixture_root, "project_tasks.json", _project_task
        ),
        aliases=_load_entities(fixture_root, "aliases.json", _alias),
        security_contexts=_load_entities(
            fixture_root, "security_scopes.json", _security_context
        ),
        purchase_order_cases=_purchase_order_cases(manifest),
    )
    _validate_fixture_set(fixture_set, _security_scope_ships(manifest))
    return fixture_set
```

Manifest validation must require exact top-level keys and exact constants from Global Constraints, including equality between its parsed scope mapping and `_EXPECTED_SECURITY_SCOPE_SHIPS`. `_validate_fixture_set` must perform the numbered checks in spec section 7 against `_EXPECTED_SECURITY_SCOPE_SHIPS`, including same-ship checks for Drawing→ShipSystem, Equipment→ShipSystem/Drawing, BOM drawing/equipment, and PO equipment. Treat an order as overdue only when `status == "OPEN"`, `actual_date is None`, `promised_date is not None`, and `promised_date < as_of_date`; non-overdue uses `promised_date >= as_of_date`; delivered requires `status == "DELIVERED"` and non-null `actual_date`.

- [ ] **Step 4: Run focused loader tests to verify GREEN**

Run the Step 2 command. Expected: `2 passed`.

- [ ] **Step 5: Add malformed-copy validation tests**

Append this copy/mutation helper and parameterized test:

```python
import shutil
from collections.abc import Callable


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


@pytest.mark.parametrize(
    ("file_name", "mutate", "category"),
    [
        ("manifest.json", lambda value: value.update(synthetic=False), "manifest"),
        ("ships.json", lambda value: value[0].update(source_system="erp"), "provenance"),
        ("ships.json", lambda value: value[0].update(unexpected=True), "schema"),
        ("ships.json", lambda value: value[1].update(id=value[0]["id"]), "duplicate id"),
        ("ships.json", lambda value: value[1].update(source_id=value[0]["source_id"]), "duplicate source"),
        ("bom_items.json", lambda value: value[0].update(quantity=12.5), "schema"),
        ("equipment.json", lambda value: value[0].update(ship_id="80000000-0000-0000-0000-000000000002"), "relationship"),
        ("aliases.json", lambda value: value[0].update(entity_id="80000000-0000-0000-0000-000000000099"), "relationship"),
        ("manifest.json", lambda value: value["purchase_order_cases"].update(overdue_ids=["80000000-0000-0000-0000-000000000073"]), "purchase-order case"),
        ("security_scopes.json", lambda value: value[0].update(allowed_ship_ids=["80000000-0000-0000-0000-000000000002"]), "security scope"),
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
    assert category in message
    assert str(root) not in message
    assert "SYN-ALPHA" not in message
```

Also add a separate invalid-JSON test that writes `{` to copied `ships.json` and expects `FixtureValidationError` containing `ships.json: invalid JSON` without the root path.

- [ ] **Step 6: Run validation tests RED then implement the missing checks**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_fixture_loader.py -k 'rejects_invalid or invalid_json' -v
```

Expected initial result: at least one FAIL for every not-yet-implemented validation category. Add only the private validation needed for those failures, then rerun until all parameter cases pass.

- [ ] **Step 7: Run the relevant non-database quality gate**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_fixture_loader.py -k 'not persist and not resolution' -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check tests/fixtures tests/integration/test_fixture_loader.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy tests/fixtures tests/integration/test_fixture_loader.py
```

Expected: all selected tests pass, Ruff exits 0, mypy reports success.

- [ ] **Step 8: Commit the strict loader slice**

```bash
git add tests/fixtures/__init__.py tests/fixtures/loader.py tests/integration/test_fixture_loader.py
git commit -m "test: add strict synthetic fixture loader"
```

---

### Task 3: Atomic repository persistence and recovery

**Files:**
- Modify: `tests/fixtures/loader.py`
- Modify: `tests/integration/test_fixture_loader.py`

**Interfaces:**
- Consumes: validated `ShipyardFixtureSet`, caller-owned SQLAlchemy `Session`, `DomainRepository.insert`, and `AliasRepository.insert`.
- Produces: `persist_shipyard_fixture_set(session: Session, fixture_set: ShipyardFixtureSet) -> None` with all-or-nothing savepoint behavior and no commit.

- [ ] **Step 1: Write failing repository round-trip test**

Append a test that imports `Session`, every domain type, `AliasRepository`, and `DomainRepository`, then executes:

```python
def test_persisted_fixture_graph_round_trips_through_public_repositories(
    migrated_session: Session,
) -> None:
    fixtures = load_shipyard_fixture_set()
    persist_shipyard_fixture_set(migrated_session, fixtures)
    repository = DomainRepository(migrated_session)
    for record in fixtures.ships:
        assert repository.get(Ship, record.id) == record
    for record in fixtures.ship_systems:
        assert repository.get(ShipSystem, record.id) == record
    for record in fixtures.drawings:
        assert repository.get(Drawing, record.id) == record
    for record in fixtures.equipment:
        assert repository.get(Equipment, record.id) == record
    for record in fixtures.materials:
        assert repository.get(Material, record.id) == record
    for record in fixtures.suppliers:
        assert repository.get(Supplier, record.id) == record
    for record in fixtures.bom_items:
        assert repository.get(BOMItem, record.id) == record
    for record in fixtures.purchase_orders:
        assert repository.get(PurchaseOrder, record.id) == record
    for record in fixtures.project_tasks:
        assert repository.get(ProjectTask, record.id) == record
    aliases = AliasRepository(migrated_session)
    for alias in fixtures.aliases:
        assert aliases.resolve(alias.entity_type, alias.alias) == alias
```

- [ ] **Step 2: Run the round-trip test to verify RED**

Run:

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_fixture_loader.py::test_persisted_fixture_graph_round_trips_through_public_repositories -v
```

Expected: FAIL because `persist_shipyard_fixture_set` still has no implementation.

- [ ] **Step 3: Implement ordered repository persistence**

Add the following implementation. It reuses all graph and scenario checks against the trusted `_EXPECTED_SECURITY_SCOPE_SHIPS` mapping before opening the savepoint:

```python
def persist_shipyard_fixture_set(
    session: Session,
    fixture_set: ShipyardFixtureSet,
) -> None:
    _validate_fixture_set(fixture_set, _EXPECTED_SECURITY_SCOPE_SHIPS)
    with session.begin_nested():
        domain_repository = DomainRepository(session)
        for records in (
            fixture_set.ships,
            fixture_set.ship_systems,
            fixture_set.drawings,
            fixture_set.equipment,
            fixture_set.materials,
            fixture_set.suppliers,
            fixture_set.bom_items,
            fixture_set.purchase_orders,
            fixture_set.project_tasks,
        ):
            for record in records:
                domain_repository.insert(record)
        alias_repository = AliasRepository(session)
        for alias in fixture_set.aliases:
            alias_repository.insert(alias)
```

Do not catch or translate repository exceptions: their existing safe messages must propagate, while the outer savepoint rolls back the whole fixture set.

- [ ] **Step 4: Run the round-trip test to verify GREEN**

Run the Step 2 command. Expected: `1 passed` with zero skips.

- [ ] **Step 5: Write and pass transaction-ownership, duplicate, and rollback tests**

Add these exact tests (and imports for `select`, `literal`, `EntityAlias`,
`AliasPersistenceError`, and `DomainPersistenceError`):

```python
ALPHA_SHIP_ID = UUID("80000000-0000-0000-0000-000000000001")


def test_persistence_leaves_commit_and_rollback_to_caller(
    migrated_session: Session,
) -> None:
    persist_shipyard_fixture_set(migrated_session, load_shipyard_fixture_set())
    assert DomainRepository(migrated_session).get(Ship, ALPHA_SHIP_ID) is not None
    migrated_session.rollback()
    assert DomainRepository(migrated_session).get(Ship, ALPHA_SHIP_ID) is None


def test_duplicate_persistence_fails_without_overwriting_first_dataset(
    migrated_session: Session,
) -> None:
    fixtures = load_shipyard_fixture_set()
    persist_shipyard_fixture_set(migrated_session, fixtures)
    with pytest.raises(DomainPersistenceError):
        persist_shipyard_fixture_set(migrated_session, fixtures)
    assert DomainRepository(migrated_session).get(Ship, ALPHA_SHIP_ID) == fixtures.ships[0]


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
```

Before implementing any adjustment, run each new test by exact node ID and confirm it fails for the intended missing behavior. After implementation, run:

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_fixture_loader.py -k 'persist or transaction or rollback or duplicate' -v
```

Expected: all selected tests pass with zero skips.

- [ ] **Step 6: Commit the persistence slice**

```bash
git add tests/fixtures/loader.py tests/integration/test_fixture_loader.py
git commit -m "test: persist synthetic fixtures atomically"
```

---

### Task 4: Alias exactness and two-ship authorization isolation

**Files:**
- Modify: `tests/integration/test_fixture_loader.py`

**Interfaces:**
- Consumes: persisted fixture set, `AliasRepository`, `DomainRepository.get`, and `EntityResolutionService.resolve`.
- Produces: acceptance evidence that fixture aliases are usable and Equipment resolution cannot cross fixture security scopes.

- [ ] **Step 1: Write the failing authorization scenario test**

Append:

```python
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
```

- [ ] **Step 2: Run the authorization test before any correction**

Run:

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_fixture_loader.py::test_fixture_equipment_aliases_respect_both_ship_security_scopes -v
```

Expected: PASS if Tasks 2-3 correctly honored the approved interfaces. If it fails, treat that as RED and correct only the fixture loader/data wiring; do not modify `EntityResolutionService` or weaken authorization.

- [ ] **Step 3: Add explicit supplier alias assertions**

Append the exact supplier test below. Run its exact node ID and correct only
fixture data/loader behavior if it fails.

```python
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
```

- [ ] **Step 4: Run all Task 008 integration tests and adjacent suites**

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_fixture_loader.py -v
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/domain tests/unit/services/test_auth_service.py tests/unit/services/test_entity_resolution_service.py tests/integration/test_domain_repository.py tests/integration/test_entity_alias_repository.py -v
```

Expected: all tests pass; database-bearing commands report zero skips.

- [ ] **Step 5: Commit the acceptance/security slice**

```bash
git add tests/integration/test_fixture_loader.py
git commit -m "test: verify synthetic fixture scope isolation"
```

---

### Task 5: Usage documentation and complete verification

**Files:**
- Create: `tests/fixtures/README.md`
- Modify only if verification exposes a Task 008 defect: Task 008 files listed above.

**Interfaces:**
- Consumes: final loader and persistence contracts.
- Produces: usage guidance and final Definition-of-Done evidence.

- [ ] **Step 1: Write `tests/fixtures/README.md`**

Document these exact points and examples:

```python
from tests.fixtures import load_shipyard_fixture_set

fixtures = load_shipyard_fixture_set()
assert fixtures.dataset_id == "synthetic-shipyard-v1"
```

```python
from sqlalchemy.orm import Session

from tests.fixtures import load_shipyard_fixture_set, persist_shipyard_fixture_set

with Session(engine) as session, session.begin():
    persist_shipyard_fixture_set(session, load_shipyard_fixture_set())
    # The caller decides whether the outer transaction commits or rolls back.
```

State that the dataset is synthetic-only, version 1, fixed at 2026-08-18, and contains no real customer/company data. List every JSON file. Explain exact aliases, Alpha/Beta singleton ship scopes, no fuzzy aliasing, validation-before-write, no internal commit, and intentional failure on duplicate load. Include this protected command:

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test .venv/bin/python -m pytest tests/integration/test_fixture_loader.py -v
```

- [ ] **Step 2: Run diff hygiene and synthetic-data review**

```bash
git diff --check b7acf6e...HEAD
git diff --name-only b7acf6e...HEAD
rg -n "Wärtsilä|customer|supplier|password|secret|token" tests/fixtures
```

Expected: diff check exits 0; changed paths are only the approved design/plan and Task 008 fixture/test files; matches for `customer` and `supplier` occur only in visibly synthetic schema/data/docs; no real brand, password, secret, or token appears.

- [ ] **Step 3: Run the complete Definition-of-Done gate**

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test make check PYTHON=/Users/wuhao/Documents/shipyard-ai/.venv/bin/python
```

Expected: dependency check passes; full pytest suite passes with zero Task 008 skips; Ruff exits 0; mypy reports success.

- [ ] **Step 4: Verify acceptance criteria explicitly**

Run:

```bash
env TEST_DATABASE_URL=postgresql+psycopg://shipyard:shipyard_dev@127.0.0.1:55432/shipyard_ai_test /Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_fixture_loader.py -v
```

Record evidence for all four acceptance criteria:

1. synthetic-only manifest/provenance and human diff review;
2. manifest-backed overdue, non-overdue, boundary, and delivered PO cases;
3. five explicit alias cases and two mutually isolated security scopes;
4. deterministic pure loader plus caller-owned atomic repository persistence.

- [ ] **Step 5: Commit documentation and any verified Task 008-only correction**

```bash
git add tests/fixtures/README.md tests/fixtures tests/integration/test_fixture_loader.py
git commit -m "docs: explain synthetic fixture usage"
```

- [ ] **Step 6: Request final two-stage review before integration**

Run a specification-compliance review against `tasks/008-synthetic-fixtures.md`, `AGENTS.md`, and the approved spec, followed by a code-quality/security review. Resolve only verified Task 008 findings using TDD and rerun Step 3 after every material correction. Do not merge or begin Task 009 until the user authorizes integration.
