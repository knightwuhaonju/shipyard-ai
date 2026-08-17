import ast
import sys
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, TypedDict, cast
from uuid import UUID

import pytest


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
BOM_ITEM_ID = UUID("00000000-0000-0000-0000-000000000007")
PURCHASE_ORDER_ID = UUID("00000000-0000-0000-0000-000000000008")
PROJECT_TASK_ID = UUID("00000000-0000-0000-0000-000000000009")


def _source_fields(entity_id: UUID, source_id: str) -> _SourceFields:
    return {
        "id": entity_id,
        "source_system": "synthetic-erp",
        "source_id": source_id,
        "source_updated_at": SOURCE_UPDATED_AT,
    }


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
    assert purchase_order.actual_date is not None
    assert purchase_order.required_date is not None
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
