from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from decimal import Decimal
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
