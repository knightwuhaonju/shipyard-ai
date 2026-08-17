# Task 005 Core Domain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build immutable, framework-independent V1 shipyard domain values and nine sourced entities with explicit provenance and tested invariants.

**Architecture:** Standard-library frozen dataclasses hold canonical entities, while small `Decimal` value objects enforce quantity and progress rules. Every entity exposes direct source metadata and internal UUIDs; persistence, transport, authorization, and source normalization remain outside the domain package.

**Tech Stack:** Python 3.12+, standard-library `dataclasses`, `datetime`, `decimal`, and `uuid`; pytest 8.x; Ruff 0.9.x; mypy 1.14.x.

## Global Constraints

- Implement only `tasks/005-domain-core.md`; do not begin Task 006.
- `packages/domain` uses Python standard-library imports only and must not import FastAPI, Pydantic, SQLAlchemy, database drivers, or LLM SDKs.
- ERP/MES/PLM or approved replicas remain the source of truth for live business state.
- Every public entity directly exposes `source_system`, `source_id`, and timezone-aware `source_updated_at`.
- Canonical `id` and relationship IDs are UUID instances and remain separate from string source IDs.
- Entities and value objects are frozen and slotted; invalid normalized state fails during construction.
- Quantities use finite `Decimal` values greater than zero.
- Progress uses finite `Decimal` values in the inclusive `0.0-1.0` range.
- `BOMItem` requires a drawing or equipment target; `PurchaseOrder` requires a material or equipment target; both targets are allowed in each case.
- Required and present optional text is non-blank; business dates are `datetime.date`, not `datetime.datetime`.
- Purchase-order required/promised/actual dates are not reordered or constrained relative to one another.
- Validation errors name only the field and rule, never the rejected value or customer/source content.
- Unit tests use synthetic data, no network, no database, and no external model calls.
- Each behavior group follows confirmed RED, minimal GREEN, focused verification, relevant suite, Ruff, and mypy.

## File Structure

- `packages/domain/value_objects.py`: domain validation error, positive quantity, and canonical progress.
- `packages/domain/entities.py`: private sourced base, validation helpers, and the nine public entities.
- `packages/domain/__init__.py`: explicit public domain API exports.
- `tests/unit/domain/test_entities.py`: synthetic construction, provenance, invariants, immutability, and import-boundary coverage.
- `docs/02-domain-model.md`: public type, provenance, relationship, and invariant semantics for later adapters and persistence.

---

### Task 1: Constrained Numeric Value Objects

**Files:**
- Create: `packages/domain/__init__.py`
- Create: `packages/domain/value_objects.py`
- Create: `tests/unit/domain/test_entities.py`

**Interfaces:**
- Consumes: standard-library `Decimal`.
- Produces: `DomainValidationError`, `PositiveQuantity(value: Decimal)`, and `Progress(value: Decimal)`.

- [ ] **Step 1: Write failing value-object tests**

Create `tests/unit/domain/test_entities.py`:

```python
from dataclasses import FrozenInstanceError
from decimal import Decimal
from typing import Any, cast

import pytest


def test_positive_quantity_accepts_only_finite_positive_decimal() -> None:
    from packages.domain.value_objects import PositiveQuantity

    quantity = PositiveQuantity(Decimal("12.50"))

    assert quantity.value == Decimal("12.50")


@pytest.mark.parametrize(
    "value",
    [Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity")],
)
def test_positive_quantity_rejects_non_positive_or_non_finite_values(
    value: Decimal,
) -> None:
    from packages.domain.value_objects import (
        DomainValidationError,
        PositiveQuantity,
    )

    with pytest.raises(
        DomainValidationError,
        match="^quantity must be finite and greater than zero$",
    ):
        PositiveQuantity(value)


def test_positive_quantity_rejects_non_decimal_without_echoing_value() -> None:
    from packages.domain.value_objects import (
        DomainValidationError,
        PositiveQuantity,
    )

    secret_value = "customer-sensitive-quantity"
    with pytest.raises(DomainValidationError) as captured:
        PositiveQuantity(cast(Any, secret_value))

    assert str(captured.value) == "quantity must be a Decimal"
    assert secret_value not in str(captured.value)


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("0.5"), Decimal("1")])
def test_progress_accepts_inclusive_canonical_range(value: Decimal) -> None:
    from packages.domain.value_objects import Progress

    assert Progress(value).value == value


def test_progress_rejects_non_decimal_without_echoing_value() -> None:
    from packages.domain.value_objects import DomainValidationError, Progress

    secret_value = "customer-sensitive-progress"
    with pytest.raises(DomainValidationError) as captured:
        Progress(cast(Any, secret_value))

    assert str(captured.value) == "progress must be a Decimal"
    assert secret_value not in str(captured.value)


@pytest.mark.parametrize(
    "value",
    [Decimal("-0.01"), Decimal("1.01"), Decimal("NaN"), Decimal("Infinity")],
)
def test_progress_rejects_out_of_range_or_non_finite_values(value: Decimal) -> None:
    from packages.domain.value_objects import DomainValidationError, Progress

    with pytest.raises(
        DomainValidationError,
        match="^progress must be finite and between zero and one$",
    ):
        Progress(value)


def test_numeric_value_objects_are_immutable() -> None:
    from packages.domain.value_objects import PositiveQuantity, Progress

    quantity = PositiveQuantity(Decimal("1"))
    progress = Progress(Decimal("0.5"))

    with pytest.raises(FrozenInstanceError):
        cast(Any, quantity).value = Decimal("2")
    with pytest.raises(FrozenInstanceError):
        cast(Any, progress).value = Decimal("0.7")
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/domain/test_entities.py -v
```

Expected: collection succeeds and tests fail with `ModuleNotFoundError: No module named 'packages.domain'`.

- [ ] **Step 3: Implement the minimum value objects**

Create `packages/domain/value_objects.py`:

```python
"""Framework-independent constrained domain values."""

from dataclasses import dataclass
from decimal import Decimal


class DomainValidationError(ValueError):
    """Raised when normalized data violates a domain invariant."""


@dataclass(frozen=True, slots=True)
class PositiveQuantity:
    """A finite quantity strictly greater than zero."""

    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise DomainValidationError("quantity must be a Decimal")
        if not self.value.is_finite() or self.value <= 0:
            raise DomainValidationError(
                "quantity must be finite and greater than zero"
            )


@dataclass(frozen=True, slots=True)
class Progress:
    """Canonical finite progress ratio in the inclusive zero-to-one range."""

    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise DomainValidationError("progress must be a Decimal")
        if (
            not self.value.is_finite()
            or not Decimal("0") <= self.value <= Decimal("1")
        ):
            raise DomainValidationError(
                "progress must be finite and between zero and one"
            )
```

Create `packages/domain/__init__.py` with the value-object exports available at
this stage:

```python
"""Framework-independent Shipyard AI domain model."""

from packages.domain.value_objects import (
    DomainValidationError,
    PositiveQuantity,
    Progress,
)

__all__ = ["DomainValidationError", "PositiveQuantity", "Progress"]
```

- [ ] **Step 4: Run the focused tests and confirm GREEN**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/domain/test_entities.py -v
```

Expected: all value-object cases pass.

- [ ] **Step 5: Run focused static checks**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check packages/domain tests/unit/domain/test_entities.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy packages/domain tests/unit/domain/test_entities.py
```

Expected: Ruff and mypy pass.

- [ ] **Step 6: Commit the value objects**

```bash
git add packages/domain tests/unit/domain/test_entities.py
git commit -m "feat: add constrained domain values"
```

---

### Task 2: Sourced Base and Reference Entities

**Files:**
- Create: `packages/domain/entities.py`
- Modify: `tests/unit/domain/test_entities.py`

**Interfaces:**
- Consumes: `DomainValidationError`.
- Produces: `Ship`, `ShipSystem`, `Drawing`, `Equipment`, `Material`, and `Supplier`, each with direct canonical/source fields.

- [ ] **Step 1: Add failing coherent-graph and source-invariant tests**

Add these imports and helpers to `tests/unit/domain/test_entities.py`:

```python
from datetime import UTC, date, datetime
from typing import TypedDict
from uuid import UUID


class _SourceFields(TypedDict):
    id: UUID
    source_system: str
    source_id: str
    source_updated_at: datetime


SOURCE_UPDATED_AT = datetime(2026, 8, 17, 8, 0, tzinfo=UTC)
SHIP_ID = UUID("00000000-0000-0000-0000-000000000001")
SYSTEM_ID = UUID("00000000-0000-0000-0000-000000000002")
DRAWING_ID = UUID("00000000-0000-0000-0000-000000000003")
EQUIPMENT_ID = UUID("00000000-0000-0000-0000-000000000004")
MATERIAL_ID = UUID("00000000-0000-0000-0000-000000000005")
SUPPLIER_ID = UUID("00000000-0000-0000-0000-000000000006")


def _source_fields(entity_id: UUID, source_id: str) -> _SourceFields:
    return {
        "id": entity_id,
        "source_system": "synthetic-erp",
        "source_id": source_id,
        "source_updated_at": SOURCE_UPDATED_AT,
    }
```

Append the tests:

```python
def test_reference_entities_form_a_sourced_synthetic_shipyard_graph() -> None:
    from packages.domain.entities import (
        Drawing,
        Equipment,
        Material,
        Ship,
        ShipSystem,
        Supplier,
    )

    ship = Ship(
        **_source_fields(SHIP_ID, "erp-ship-001"),
        ship_code="SHIP-001",
        name="Synthetic Vessel",
        planned_delivery_date=date(2027, 6, 1),
    )
    system = ShipSystem(
        **_source_fields(SYSTEM_ID, "plm-system-001"),
        ship_id=ship.id,
        system_code="SYS-BALLAST",
        name="Ballast System",
    )
    drawing = Drawing(
        **_source_fields(DRAWING_ID, "plm-drawing-001"),
        ship_id=ship.id,
        system_id=system.id,
        drawing_no="DWG-001",
        title="Synthetic Ballast Arrangement",
        revision="A",
    )
    equipment = Equipment(
        **_source_fields(EQUIPMENT_ID, "plm-equipment-001"),
        ship_id=ship.id,
        system_id=system.id,
        drawing_id=drawing.id,
        equipment_code="EQ-PUMP-001",
        manufacturer="Synthetic Manufacturer",
    )
    material = Material(
        **_source_fields(MATERIAL_ID, "erp-material-001"),
        material_code="MAT-001",
        description="Synthetic pipe section",
        unit="m",
    )
    supplier = Supplier(
        **_source_fields(SUPPLIER_ID, "erp-supplier-001"),
        supplier_code="SUP-001",
        canonical_name="Synthetic Supplier",
    )

    entities = (ship, system, drawing, equipment, material, supplier)
    assert all(entity.source_system for entity in entities)
    assert all(entity.source_id for entity in entities)
    assert all(entity.source_updated_at is SOURCE_UPDATED_AT for entity in entities)
    assert system.ship_id == ship.id
    assert drawing.system_id == system.id
    assert equipment.drawing_id == drawing.id


def test_canonical_id_cannot_be_replaced_by_source_string() -> None:
    from packages.domain.entities import Ship
    from packages.domain.value_objects import DomainValidationError

    with pytest.raises(DomainValidationError, match="^id must be a UUID$"):
        Ship(
            **cast(
                Any,
                {
                    "id": "erp-ship-001",
                    "source_system": "synthetic-erp",
                    "source_id": "erp-ship-001",
                    "source_updated_at": SOURCE_UPDATED_AT,
                },
            ),
            ship_code="SHIP-001",
        )


def test_relationship_id_cannot_be_replaced_by_source_string() -> None:
    from packages.domain.entities import ShipSystem
    from packages.domain.value_objects import DomainValidationError

    with pytest.raises(DomainValidationError, match="^ship_id must be a UUID$"):
        ShipSystem(
            **_source_fields(SYSTEM_ID, "plm-system-001"),
            ship_id=cast(Any, "erp-ship-001"),
            system_code="SYS-001",
            name="Synthetic system",
        )


@pytest.mark.parametrize("field", ["source_system", "source_id"])
def test_source_identity_fields_must_be_non_blank(field: str) -> None:
    from packages.domain.entities import Ship
    from packages.domain.value_objects import DomainValidationError

    values: dict[str, object] = {
        **_source_fields(SHIP_ID, "erp-ship-001"),
        "ship_code": "SHIP-001",
    }
    values[field] = "   "

    with pytest.raises(DomainValidationError, match=rf"^{field} must be non-blank$"):
        cast(Any, Ship)(**values)


def test_source_updated_at_must_be_timezone_aware() -> None:
    from packages.domain.entities import Ship
    from packages.domain.value_objects import DomainValidationError

    with pytest.raises(
        DomainValidationError,
        match="^source_updated_at must be timezone-aware$",
    ):
        Ship(
            id=SHIP_ID,
            source_system="synthetic-erp",
            source_id="erp-ship-001",
            source_updated_at=datetime(2026, 8, 17, 8, 0),
            ship_code="SHIP-001",
        )


def test_required_and_present_optional_text_must_be_non_blank() -> None:
    from packages.domain.entities import Equipment, Ship
    from packages.domain.value_objects import DomainValidationError

    with pytest.raises(DomainValidationError, match="^ship_code must be non-blank$"):
        Ship(**_source_fields(SHIP_ID, "erp-ship-001"), ship_code=" ")
    with pytest.raises(
        DomainValidationError,
        match="^manufacturer must be non-blank when provided$",
    ):
        Equipment(
            **_source_fields(EQUIPMENT_ID, "plm-equipment-001"),
            ship_id=SHIP_ID,
            equipment_code="EQ-001",
            manufacturer=" ",
        )


def test_business_date_rejects_datetime_values() -> None:
    from packages.domain.entities import Ship
    from packages.domain.value_objects import DomainValidationError

    with pytest.raises(
        DomainValidationError,
        match="^planned_delivery_date must be a date$",
    ):
        Ship(
            **_source_fields(SHIP_ID, "erp-ship-001"),
            ship_code="SHIP-001",
            planned_delivery_date=cast(Any, SOURCE_UPDATED_AT),
        )
```

- [ ] **Step 2: Run the new entity tests and confirm RED**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/domain/test_entities.py::test_reference_entities_form_a_sourced_synthetic_shipyard_graph tests/unit/domain/test_entities.py::test_canonical_id_cannot_be_replaced_by_source_string tests/unit/domain/test_entities.py::test_relationship_id_cannot_be_replaced_by_source_string tests/unit/domain/test_entities.py::test_source_identity_fields_must_be_non_blank tests/unit/domain/test_entities.py::test_source_updated_at_must_be_timezone_aware tests/unit/domain/test_entities.py::test_required_and_present_optional_text_must_be_non_blank tests/unit/domain/test_entities.py::test_business_date_rejects_datetime_values -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'packages.domain.entities'`.

- [ ] **Step 3: Implement sourced validation and six reference entities**

Create `packages/domain/entities.py`:

```python
"""Immutable canonical shipyard entities with explicit source provenance."""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from packages.domain.value_objects import DomainValidationError


def _require_uuid(field: str, value: object) -> None:
    if not isinstance(value, UUID):
        raise DomainValidationError(f"{field} must be a UUID")


def _require_optional_uuid(field: str, value: object | None) -> None:
    if value is not None:
        _require_uuid(field, value)


def _require_text(field: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"{field} must be non-blank")


def _require_optional_text(field: str, value: object | None) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise DomainValidationError(f"{field} must be non-blank when provided")


def _require_optional_date(field: str, value: object | None) -> None:
    if value is not None and type(value) is not date:
        raise DomainValidationError(f"{field} must be a date")


@dataclass(frozen=True, slots=True, kw_only=True)
class _SourcedEntity:
    id: UUID
    source_system: str
    source_id: str
    source_updated_at: datetime

    def __post_init__(self) -> None:
        _require_uuid("id", self.id)
        _require_text("source_system", self.source_system)
        _require_text("source_id", self.source_id)
        if (
            not isinstance(self.source_updated_at, datetime)
            or self.source_updated_at.tzinfo is None
            or self.source_updated_at.utcoffset() is None
        ):
            raise DomainValidationError(
                "source_updated_at must be timezone-aware"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class Ship(_SourcedEntity):
    ship_code: str
    name: str | None = None
    customer_name: str | None = None
    vessel_type: str | None = None
    planned_delivery_date: date | None = None

    def __post_init__(self) -> None:
        _SourcedEntity.__post_init__(self)
        _require_text("ship_code", self.ship_code)
        _require_optional_text("name", self.name)
        _require_optional_text("customer_name", self.customer_name)
        _require_optional_text("vessel_type", self.vessel_type)
        _require_optional_date("planned_delivery_date", self.planned_delivery_date)


@dataclass(frozen=True, slots=True, kw_only=True)
class ShipSystem(_SourcedEntity):
    ship_id: UUID
    system_code: str
    name: str

    def __post_init__(self) -> None:
        _SourcedEntity.__post_init__(self)
        _require_uuid("ship_id", self.ship_id)
        _require_text("system_code", self.system_code)
        _require_text("name", self.name)


@dataclass(frozen=True, slots=True, kw_only=True)
class Drawing(_SourcedEntity):
    ship_id: UUID
    drawing_no: str
    title: str
    revision: str
    system_id: UUID | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        _SourcedEntity.__post_init__(self)
        _require_uuid("ship_id", self.ship_id)
        _require_optional_uuid("system_id", self.system_id)
        _require_text("drawing_no", self.drawing_no)
        _require_text("title", self.title)
        _require_text("revision", self.revision)
        _require_optional_text("status", self.status)


@dataclass(frozen=True, slots=True, kw_only=True)
class Equipment(_SourcedEntity):
    ship_id: UUID
    equipment_code: str
    system_id: UUID | None = None
    drawing_id: UUID | None = None
    manufacturer: str | None = None
    model: str | None = None

    def __post_init__(self) -> None:
        _SourcedEntity.__post_init__(self)
        _require_uuid("ship_id", self.ship_id)
        _require_optional_uuid("system_id", self.system_id)
        _require_optional_uuid("drawing_id", self.drawing_id)
        _require_text("equipment_code", self.equipment_code)
        _require_optional_text("manufacturer", self.manufacturer)
        _require_optional_text("model", self.model)


@dataclass(frozen=True, slots=True, kw_only=True)
class Material(_SourcedEntity):
    material_code: str
    description: str
    specification: str | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        _SourcedEntity.__post_init__(self)
        _require_text("material_code", self.material_code)
        _require_text("description", self.description)
        _require_optional_text("specification", self.specification)
        _require_optional_text("unit", self.unit)


@dataclass(frozen=True, slots=True, kw_only=True)
class Supplier(_SourcedEntity):
    supplier_code: str
    canonical_name: str

    def __post_init__(self) -> None:
        _SourcedEntity.__post_init__(self)
        _require_text("supplier_code", self.supplier_code)
        _require_text("canonical_name", self.canonical_name)
```

- [ ] **Step 4: Run the complete domain test module and confirm GREEN**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/domain/test_entities.py -v
```

Expected: all value-object and reference-entity tests pass.

- [ ] **Step 5: Run focused static checks**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check packages/domain tests/unit/domain/test_entities.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy packages/domain tests/unit/domain/test_entities.py
```

Expected: Ruff and mypy pass.

- [ ] **Step 6: Commit the sourced reference entities**

```bash
git add packages/domain/entities.py tests/unit/domain/test_entities.py
git commit -m "feat: add sourced reference entities"
```

---

### Task 3: BOM, Procurement, and Project Entities

**Files:**
- Modify: `packages/domain/entities.py`
- Modify: `tests/unit/domain/test_entities.py`

**Interfaces:**
- Consumes: sourced base validation, `PositiveQuantity`, and `Progress`.
- Produces: `BOMItem`, `PurchaseOrder`, and `ProjectTask` with relationship, quantity, progress, and date invariants.

- [ ] **Step 1: Add failing operational-entity tests**

Add constants:

```python
BOM_ITEM_ID = UUID("00000000-0000-0000-0000-000000000007")
PURCHASE_ORDER_ID = UUID("00000000-0000-0000-0000-000000000008")
PROJECT_TASK_ID = UUID("00000000-0000-0000-0000-000000000009")
```

Append:

```python
def test_operational_entities_preserve_relationships_and_provenance() -> None:
    from packages.domain.entities import BOMItem, ProjectTask, PurchaseOrder
    from packages.domain.value_objects import PositiveQuantity, Progress

    bom_item = BOMItem(
        **_source_fields(BOM_ITEM_ID, "plm-bom-001"),
        drawing_id=DRAWING_ID,
        equipment_id=EQUIPMENT_ID,
        material_id=MATERIAL_ID,
        quantity=PositiveQuantity(Decimal("4.5")),
    )
    purchase_order = PurchaseOrder(
        **_source_fields(PURCHASE_ORDER_ID, "erp-po-001"),
        ship_id=SHIP_ID,
        material_id=MATERIAL_ID,
        equipment_id=EQUIPMENT_ID,
        supplier_id=SUPPLIER_ID,
        po_number="PO-001",
        quantity=PositiveQuantity(Decimal("4.5")),
        required_date=date(2026, 8, 1),
        promised_date=date(2026, 8, 15),
        actual_date=date(2026, 8, 20),
        status="DELIVERED_LATE",
        criticality="HIGH",
    )
    project_task = ProjectTask(
        **_source_fields(PROJECT_TASK_ID, "mes-task-001"),
        ship_id=SHIP_ID,
        task_code="TASK-001",
        name="Synthetic installation task",
        planned_start=date(2026, 8, 1),
        planned_end=date(2026, 8, 31),
        actual_start=date(2026, 8, 2),
        actual_end=date(2026, 9, 2),
        planned_progress=Progress(Decimal("1")),
        actual_progress=Progress(Decimal("0.75")),
        critical_path=True,
    )

    assert bom_item.material_id == MATERIAL_ID
    assert purchase_order.actual_date > purchase_order.required_date
    assert project_task.actual_progress == Progress(Decimal("0.75"))
    assert all(
        entity.source_updated_at is SOURCE_UPDATED_AT
        for entity in (bom_item, purchase_order, project_task)
    )


def test_bom_item_requires_drawing_or_equipment_target() -> None:
    from packages.domain.entities import BOMItem
    from packages.domain.value_objects import (
        DomainValidationError,
        PositiveQuantity,
    )

    with pytest.raises(
        DomainValidationError,
        match="^BOMItem requires drawing_id or equipment_id$",
    ):
        BOMItem(
            **_source_fields(BOM_ITEM_ID, "plm-bom-001"),
            material_id=MATERIAL_ID,
            quantity=PositiveQuantity(Decimal("1")),
        )


def test_purchase_order_requires_material_or_equipment_target() -> None:
    from packages.domain.entities import PurchaseOrder
    from packages.domain.value_objects import DomainValidationError

    with pytest.raises(
        DomainValidationError,
        match="^PurchaseOrder requires material_id or equipment_id$",
    ):
        PurchaseOrder(
            **_source_fields(PURCHASE_ORDER_ID, "erp-po-001"),
            ship_id=SHIP_ID,
            supplier_id=SUPPLIER_ID,
            po_number="PO-001",
            status="OPEN",
        )


@pytest.mark.parametrize(
    ("planned_start", "planned_end", "actual_start", "actual_end", "field"),
    [
        (date(2026, 8, 2), date(2026, 8, 1), None, None, "planned"),
        (None, None, date(2026, 8, 2), date(2026, 8, 1), "actual"),
    ],
)
def test_project_task_rejects_reverse_date_ranges(
    planned_start: date | None,
    planned_end: date | None,
    actual_start: date | None,
    actual_end: date | None,
    field: str,
) -> None:
    from packages.domain.entities import ProjectTask
    from packages.domain.value_objects import DomainValidationError

    with pytest.raises(
        DomainValidationError,
        match=rf"^{field}_start cannot be after {field}_end$",
    ):
        ProjectTask(
            **_source_fields(PROJECT_TASK_ID, "mes-task-001"),
            ship_id=SHIP_ID,
            task_code="TASK-001",
            name="Synthetic task",
            planned_start=planned_start,
            planned_end=planned_end,
            actual_start=actual_start,
            actual_end=actual_end,
        )


def test_operational_entities_require_domain_value_objects_and_strict_bool() -> None:
    from packages.domain.entities import BOMItem, ProjectTask, PurchaseOrder
    from packages.domain.value_objects import DomainValidationError

    with pytest.raises(
        DomainValidationError,
        match="^quantity must be a PositiveQuantity$",
    ):
        BOMItem(
            **_source_fields(BOM_ITEM_ID, "plm-bom-001"),
            drawing_id=DRAWING_ID,
            material_id=MATERIAL_ID,
            quantity=cast(Any, Decimal("1")),
        )
    with pytest.raises(
        DomainValidationError,
        match="^quantity must be a PositiveQuantity when provided$",
    ):
        PurchaseOrder(
            **_source_fields(PURCHASE_ORDER_ID, "erp-po-001"),
            ship_id=SHIP_ID,
            material_id=MATERIAL_ID,
            supplier_id=SUPPLIER_ID,
            po_number="PO-001",
            status="OPEN",
            quantity=cast(Any, Decimal("1")),
        )
    with pytest.raises(
        DomainValidationError,
        match="^critical_path must be a bool when provided$",
    ):
        ProjectTask(
            **_source_fields(PROJECT_TASK_ID, "mes-task-001"),
            ship_id=SHIP_ID,
            task_code="TASK-001",
            name="Synthetic task",
            critical_path=cast(Any, 1),
        )


def test_operational_text_and_progress_fields_reject_unvalidated_values() -> None:
    from packages.domain.entities import ProjectTask, PurchaseOrder
    from packages.domain.value_objects import DomainValidationError

    with pytest.raises(DomainValidationError, match="^status must be non-blank$"):
        PurchaseOrder(
            **_source_fields(PURCHASE_ORDER_ID, "erp-po-001"),
            ship_id=SHIP_ID,
            material_id=MATERIAL_ID,
            supplier_id=SUPPLIER_ID,
            po_number="PO-001",
            status=" ",
        )
    with pytest.raises(
        DomainValidationError,
        match="^planned_progress must be a Progress when provided$",
    ):
        ProjectTask(
            **_source_fields(PROJECT_TASK_ID, "mes-task-001"),
            ship_id=SHIP_ID,
            task_code="TASK-001",
            name="Synthetic task",
            planned_progress=cast(Any, Decimal("0.5")),
        )
```

- [ ] **Step 2: Run the operational tests and confirm RED**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/domain/test_entities.py::test_operational_entities_preserve_relationships_and_provenance tests/unit/domain/test_entities.py::test_bom_item_requires_drawing_or_equipment_target tests/unit/domain/test_entities.py::test_purchase_order_requires_material_or_equipment_target tests/unit/domain/test_entities.py::test_project_task_rejects_reverse_date_ranges tests/unit/domain/test_entities.py::test_operational_entities_require_domain_value_objects_and_strict_bool tests/unit/domain/test_entities.py::test_operational_text_and_progress_fields_reject_unvalidated_values -v
```

Expected: FAIL because `BOMItem`, `PurchaseOrder`, and `ProjectTask` are not yet defined.

- [ ] **Step 3: Add operational validation helpers and entities**

Update the value-object import in `packages/domain/entities.py`:

```python
from packages.domain.value_objects import (
    DomainValidationError,
    PositiveQuantity,
    Progress,
)
```

Add helpers:

```python
def _require_date_range(
    prefix: str,
    start: date | None,
    end: date | None,
) -> None:
    _require_optional_date(f"{prefix}_start", start)
    _require_optional_date(f"{prefix}_end", end)
    if start is not None and end is not None and start > end:
        raise DomainValidationError(
            f"{prefix}_start cannot be after {prefix}_end"
        )


def _require_optional_quantity(value: object | None) -> None:
    if value is not None and not isinstance(value, PositiveQuantity):
        raise DomainValidationError(
            "quantity must be a PositiveQuantity when provided"
        )


def _require_optional_progress(field: str, value: object | None) -> None:
    if value is not None and not isinstance(value, Progress):
        raise DomainValidationError(f"{field} must be a Progress when provided")
```

Append the entities:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class BOMItem(_SourcedEntity):
    material_id: UUID
    quantity: PositiveQuantity
    drawing_id: UUID | None = None
    equipment_id: UUID | None = None

    def __post_init__(self) -> None:
        _SourcedEntity.__post_init__(self)
        _require_uuid("material_id", self.material_id)
        _require_optional_uuid("drawing_id", self.drawing_id)
        _require_optional_uuid("equipment_id", self.equipment_id)
        if self.drawing_id is None and self.equipment_id is None:
            raise DomainValidationError(
                "BOMItem requires drawing_id or equipment_id"
            )
        if not isinstance(self.quantity, PositiveQuantity):
            raise DomainValidationError("quantity must be a PositiveQuantity")


@dataclass(frozen=True, slots=True, kw_only=True)
class PurchaseOrder(_SourcedEntity):
    ship_id: UUID
    supplier_id: UUID
    po_number: str
    status: str
    material_id: UUID | None = None
    equipment_id: UUID | None = None
    quantity: PositiveQuantity | None = None
    required_date: date | None = None
    promised_date: date | None = None
    actual_date: date | None = None
    criticality: str | None = None

    def __post_init__(self) -> None:
        _SourcedEntity.__post_init__(self)
        _require_uuid("ship_id", self.ship_id)
        _require_uuid("supplier_id", self.supplier_id)
        _require_optional_uuid("material_id", self.material_id)
        _require_optional_uuid("equipment_id", self.equipment_id)
        if self.material_id is None and self.equipment_id is None:
            raise DomainValidationError(
                "PurchaseOrder requires material_id or equipment_id"
            )
        _require_text("po_number", self.po_number)
        _require_text("status", self.status)
        _require_optional_quantity(self.quantity)
        _require_optional_date("required_date", self.required_date)
        _require_optional_date("promised_date", self.promised_date)
        _require_optional_date("actual_date", self.actual_date)
        _require_optional_text("criticality", self.criticality)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectTask(_SourcedEntity):
    ship_id: UUID
    task_code: str
    name: str
    planned_start: date | None = None
    planned_end: date | None = None
    actual_start: date | None = None
    actual_end: date | None = None
    planned_progress: Progress | None = None
    actual_progress: Progress | None = None
    critical_path: bool | None = None

    def __post_init__(self) -> None:
        _SourcedEntity.__post_init__(self)
        _require_uuid("ship_id", self.ship_id)
        _require_text("task_code", self.task_code)
        _require_text("name", self.name)
        _require_date_range("planned", self.planned_start, self.planned_end)
        _require_date_range("actual", self.actual_start, self.actual_end)
        _require_optional_progress("planned_progress", self.planned_progress)
        _require_optional_progress("actual_progress", self.actual_progress)
        if self.critical_path is not None and type(self.critical_path) is not bool:
            raise DomainValidationError(
                "critical_path must be a bool when provided"
            )
```

- [ ] **Step 4: Run all domain tests and confirm GREEN**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/domain/test_entities.py -v
```

Expected: all domain tests pass, including late purchase-order dates preserved as data.

- [ ] **Step 5: Run focused static checks**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check packages/domain tests/unit/domain/test_entities.py
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy packages/domain tests/unit/domain/test_entities.py
```

Expected: Ruff and mypy pass.

- [ ] **Step 6: Commit operational entities**

```bash
git add packages/domain/entities.py tests/unit/domain/test_entities.py
git commit -m "feat: add operational domain entities"
```

---

### Task 4: Public Domain API and Architecture Guard

**Files:**
- Modify: `packages/domain/__init__.py`
- Modify: `tests/unit/domain/test_entities.py`

**Interfaces:**
- Consumes: all value objects and nine entity classes.
- Produces: explicit `packages.domain` exports and a standard-library-only import guard.

- [ ] **Step 1: Add failing public-API, provenance, and import-boundary tests**

Add these imports:

```python
import ast
import sys
from pathlib import Path
```

Append:

```python
def test_public_domain_api_exports_all_task_005_types() -> None:
    import packages.domain as domain

    expected = {
        "BOMItem",
        "DomainValidationError",
        "Drawing",
        "Equipment",
        "Material",
        "PositiveQuantity",
        "Progress",
        "ProjectTask",
        "PurchaseOrder",
        "Ship",
        "ShipSystem",
        "Supplier",
    }

    assert set(domain.__all__) == expected
    assert all(hasattr(domain, name) for name in expected)


def test_all_nine_entities_expose_direct_source_fields() -> None:
    from packages.domain.entities import (
        BOMItem,
        Drawing,
        Equipment,
        Material,
        ProjectTask,
        PurchaseOrder,
        Ship,
        ShipSystem,
        Supplier,
    )
    from packages.domain.value_objects import PositiveQuantity

    entities = (
        Ship(**_source_fields(SHIP_ID, "ship"), ship_code="SHIP-001"),
        ShipSystem(
            **_source_fields(SYSTEM_ID, "system"),
            ship_id=SHIP_ID,
            system_code="SYS-001",
            name="Synthetic system",
        ),
        Drawing(
            **_source_fields(DRAWING_ID, "drawing"),
            ship_id=SHIP_ID,
            drawing_no="DWG-001",
            title="Synthetic drawing",
            revision="A",
        ),
        Equipment(
            **_source_fields(EQUIPMENT_ID, "equipment"),
            ship_id=SHIP_ID,
            equipment_code="EQ-001",
        ),
        Material(
            **_source_fields(MATERIAL_ID, "material"),
            material_code="MAT-001",
            description="Synthetic material",
        ),
        BOMItem(
            **_source_fields(BOM_ITEM_ID, "bom"),
            drawing_id=DRAWING_ID,
            material_id=MATERIAL_ID,
            quantity=PositiveQuantity(Decimal("1")),
        ),
        Supplier(
            **_source_fields(SUPPLIER_ID, "supplier"),
            supplier_code="SUP-001",
            canonical_name="Synthetic supplier",
        ),
        PurchaseOrder(
            **_source_fields(PURCHASE_ORDER_ID, "po"),
            ship_id=SHIP_ID,
            material_id=MATERIAL_ID,
            supplier_id=SUPPLIER_ID,
            po_number="PO-001",
            status="OPEN",
        ),
        ProjectTask(
            **_source_fields(PROJECT_TASK_ID, "task"),
            ship_id=SHIP_ID,
            task_code="TASK-001",
            name="Synthetic task",
        ),
    )

    for entity in entities:
        assert isinstance(entity.id, UUID)
        assert entity.source_system == "synthetic-erp"
        assert entity.source_id
        assert entity.source_updated_at is SOURCE_UPDATED_AT


def test_entities_are_immutable() -> None:
    from packages.domain.entities import Ship

    ship = Ship(**_source_fields(SHIP_ID, "ship"), ship_code="SHIP-001")

    with pytest.raises(FrozenInstanceError):
        cast(Any, ship).ship_code = "CHANGED"


def test_domain_modules_use_only_standard_library_and_domain_imports() -> None:
    domain_root = Path(__file__).resolve().parents[3] / "packages" / "domain"
    allowed_roots = set(sys.stdlib_module_names) | {"__future__", "packages"}

    for module_path in domain_root.glob("*.py"):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        imported_roots = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }

        assert imported_roots <= allowed_roots, (
            f"{module_path.name} imports non-domain dependency roots: "
            f"{sorted(imported_roots - allowed_roots)}"
        )
```

- [ ] **Step 2: Run the public-API test and confirm RED**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/domain/test_entities.py::test_public_domain_api_exports_all_task_005_types -v
```

Expected: FAIL because `packages.domain.__all__` still exports only the Task 1 value objects.

- [ ] **Step 3: Export the complete public domain API**

Replace `packages/domain/__init__.py` with:

```python
"""Framework-independent Shipyard AI domain model."""

from packages.domain.entities import (
    BOMItem,
    Drawing,
    Equipment,
    Material,
    ProjectTask,
    PurchaseOrder,
    Ship,
    ShipSystem,
    Supplier,
)
from packages.domain.value_objects import (
    DomainValidationError,
    PositiveQuantity,
    Progress,
)

__all__ = [
    "BOMItem",
    "DomainValidationError",
    "Drawing",
    "Equipment",
    "Material",
    "PositiveQuantity",
    "Progress",
    "ProjectTask",
    "PurchaseOrder",
    "Ship",
    "ShipSystem",
    "Supplier",
]
```

- [ ] **Step 4: Run all domain tests and confirm GREEN**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/domain/test_entities.py -v
```

Expected: all public API, provenance, invariant, immutability, and import-boundary tests pass.

- [ ] **Step 5: Run the complete unit suite and static checks**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit -v
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check .
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy .
```

Expected: all unit tests, Ruff, and mypy pass.

- [ ] **Step 6: Commit public API and architecture guard**

```bash
git add packages/domain/__init__.py tests/unit/domain/test_entities.py
git commit -m "test: guard domain architecture and provenance"
```

---

### Task 5: Document and Verify Task 005

**Files:**
- Modify: `docs/02-domain-model.md`
- Verify: all Task 005 source and test files.

**Interfaces:**
- Consumes: final entity and value-object behavior.
- Produces: public domain rules for source adapters and Task 006 persistence mapping.

- [ ] **Step 1: Document shared canonical rules**

Add a `Canonical types and invariants` section near the top of
`docs/02-domain-model.md` containing these exact rules:

```text
- Entity and relationship IDs are internal UUIDs; source IDs remain separate strings.
- Every entity carries source_system, source_id, and timezone-aware source_updated_at.
- Business dates use date; quantities use finite positive Decimal values.
- Progress is a finite Decimal ratio in the inclusive 0.0-1.0 range.
- Required and present optional text values are non-blank.
- Entities and constrained values are immutable.
```

- [ ] **Step 2: Document relationship and date semantics**

Clarify the relevant entity sections with:

```text
- BOMItem requires at least one of drawing_id or equipment_id; both are allowed.
- PurchaseOrder requires at least one of material_id or equipment_id; both are allowed.
- Purchase-order required, promised, and actual dates preserve source facts and have no ordering invariant.
- ProjectTask planned and actual start dates cannot be after their corresponding end dates.
- Status and criticality are non-blank strings until a controlled vocabulary is defined.
```

- [ ] **Step 3: Check documentation and source diffs**

Run:

```bash
git diff --check
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check .
```

Expected: no whitespace errors and Ruff reports `All checks passed!`.

- [ ] **Step 4: Run the focused domain suite**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/domain/test_entities.py -v
```

Expected: all domain tests pass.

- [ ] **Step 5: Run the relevant deployment integration suite**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/integration/test_deployment.py tests/integration/test_quality_gate.py -v
```

Expected: all selected integration tests pass. The deployment runtime test may
need approved loopback access in the managed sandbox.

- [ ] **Step 6: Run the complete quality gate**

Run:

```bash
make check PYTHON=/Users/wuhao/Documents/shipyard-ai/.venv/bin/python
```

Expected: dependency check, all tests, Ruff, and mypy pass.

- [ ] **Step 7: Run explicit final lint and type checks for reporting**

Run:

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m ruff check .
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m mypy .
git diff --check origin/main...HEAD
```

Expected: Ruff and mypy pass and the complete branch diff has no whitespace errors.

- [ ] **Step 8: Commit public domain documentation**

```bash
git add docs/02-domain-model.md
git commit -m "docs: define canonical domain invariants"
```

- [ ] **Step 9: Request independent review**

Have a separate principal-engineer reviewer read `AGENTS.md`,
`tasks/005-domain-core.md`, the approved design, and the full
`origin/main...HEAD` diff. Require P0-P3 findings with file/range, failure
scenario, violated requirement, and smallest safe fix. The review is read-only.

- [ ] **Step 10: Resolve every P0-P2 finding with TDD**

For every P0-P2 finding, add a focused failing regression test, confirm the RED
failure, implement the smallest safe fix, rerun its focused test and the complete
quality gate, and re-review until no P0-P2 findings remain.

- [ ] **Step 11: Evaluate acceptance and stop before Task 006**

Record evidence that the domain imports only standard-library/domain modules,
all nine sourced entities expose all three source fields, internal UUIDs remain
separate from source IDs, invariants have focused tests, the complete quality
gate passes, and no Task 006 persistence or migration behavior was introduced.
