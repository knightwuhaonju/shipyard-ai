"""Strict loader for the checked-in synthetic shipyard fixture graph."""

from __future__ import annotations

import json
from collections.abc import Callable
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Never, cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from infra.postgres.alias_repository import AliasRepository
from infra.postgres.repositories import DomainRepository
from packages.contracts.auth import SecurityLevel, UserContext
from packages.domain import (
    AliasEntityType,
    BOMItem,
    DomainValidationError,
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

_DEFAULT_ROOT = Path(__file__).parent / "shipyard"
_FIXTURE_FILE_NAMES = (
    "manifest.json",
    "ships.json",
    "ship_systems.json",
    "drawings.json",
    "equipment.json",
    "materials.json",
    "bom_items.json",
    "suppliers.json",
    "purchase_orders.json",
    "project_tasks.json",
    "aliases.json",
    "security_scopes.json",
)
_EXPECTED_SECURITY_SCOPE_SHIPS = {
    "ship-alpha-only": UUID("80000000-0000-0000-0000-000000000001"),
    "ship-beta-only": UUID("80000000-0000-0000-0000-000000000002"),
}

type JsonObject = dict[str, Any]


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


def _error(file_name: str, category: str, index: int | None = None) -> Never:
    location = file_name if index is None else f"{file_name}:{index}"
    raise FixtureValidationError(f"{location}: {category}") from None


def _read_json(root: Path, file_name: str) -> Any:
    if file_name not in _FIXTURE_FILE_NAMES:
        _error(file_name, "schema")
    try:
        return json.loads((root / file_name).read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        _error(file_name, "invalid encoding")
    except json.JSONDecodeError:
        _error(file_name, "invalid JSON")
    except OSError:
        _error(file_name, "read error")


def _load_object(root: Path, file_name: str) -> JsonObject:
    value = _read_json(root, file_name)
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        _error(file_name, "manifest" if file_name == "manifest.json" else "schema")
    return cast(JsonObject, value)


def _load_entities[EntityT](
    root: Path,
    file_name: str,
    factory: Callable[[JsonObject], EntityT],
) -> tuple[EntityT, ...]:
    value = _read_json(root, file_name)
    if not isinstance(value, list):
        _error(file_name, "schema")
    entities: list[EntityT] = []
    for index, record in enumerate(value):
        if not isinstance(record, dict) or not all(
            isinstance(key, str) for key in record
        ):
            _error(file_name, "schema", index)
        try:
            entities.append(factory(record))
        except FixtureValidationError:
            raise
        except (
            DomainValidationError,
            InvalidOperation,
            KeyError,
            TypeError,
            ValidationError,
            ValueError,
        ):
            _error(file_name, "schema", index)
    return tuple(entities)


def _fields(
    record: JsonObject,
    *,
    required: AbstractSet[str],
    optional: AbstractSet[str] = frozenset(),
) -> None:
    keys = set(record)
    if required - keys or keys - (required | optional):
        raise ValueError


def _text(record: JsonObject, field: str) -> str:
    value = record[field]
    if not isinstance(value, str) or not value.strip():
        raise TypeError
    return value


def _optional_text(record: JsonObject, field: str) -> str | None:
    value = record.get(field)
    if value is None:
        return None
    return _text(record, field)


def _integer(record: JsonObject, field: str) -> int:
    value = record[field]
    if type(value) is not int:
        raise TypeError
    return value


def _boolean(record: JsonObject, field: str) -> bool:
    value = record[field]
    if type(value) is not bool:
        raise TypeError
    return value


def _uuid(record: JsonObject, field: str) -> UUID:
    value = record[field]
    if not isinstance(value, str):
        raise TypeError
    parsed = UUID(value)
    if str(parsed) != value:
        raise ValueError
    return parsed


def _optional_uuid(record: JsonObject, field: str) -> UUID | None:
    if record.get(field) is None:
        return None
    return _uuid(record, field)


def _date(record: JsonObject, field: str) -> date:
    value = record[field]
    if not isinstance(value, str):
        raise TypeError
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError
    return parsed


def _optional_date(record: JsonObject, field: str) -> date | None:
    if record.get(field) is None:
        return None
    return _date(record, field)


def _datetime(record: JsonObject, field: str) -> datetime:
    value = record[field]
    if not isinstance(value, str):
        raise TypeError
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError
    return parsed


def _quantity(record: JsonObject, field: str) -> PositiveQuantity:
    value = record[field]
    if not isinstance(value, str):
        raise TypeError
    return PositiveQuantity(Decimal(value))


def _optional_quantity(
    record: JsonObject, field: str
) -> PositiveQuantity | None:
    if record.get(field) is None:
        return None
    return _quantity(record, field)


def _optional_progress(record: JsonObject, field: str) -> Progress | None:
    value = record.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError
    return Progress(Decimal(value))


def _optional_bool(record: JsonObject, field: str) -> bool | None:
    value = record.get(field)
    if value is None:
        return None
    if type(value) is not bool:
        raise TypeError
    return value


def _text_list(record: JsonObject, field: str) -> list[str]:
    value = record[field]
    if not isinstance(value, list):
        raise TypeError
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise TypeError
        result.append(item)
    return result


def _uuid_text_list(record: JsonObject, field: str) -> list[str]:
    result = _text_list(record, field)
    for item in result:
        if str(UUID(item)) != item:
            raise ValueError
    return result


_SOURCE_FIELDS = frozenset({"id", "source_system", "source_id", "source_updated_at"})


def _ship(record: JsonObject) -> Ship:
    _fields(
        record,
        required=_SOURCE_FIELDS | {"ship_code"},
        optional={"name", "customer_name", "vessel_type", "planned_delivery_date"},
    )
    return Ship(
        id=_uuid(record, "id"),
        source_system=_text(record, "source_system"),
        source_id=_text(record, "source_id"),
        source_updated_at=_datetime(record, "source_updated_at"),
        ship_code=_text(record, "ship_code"),
        name=_optional_text(record, "name"),
        customer_name=_optional_text(record, "customer_name"),
        vessel_type=_optional_text(record, "vessel_type"),
        planned_delivery_date=_optional_date(record, "planned_delivery_date"),
    )


def _ship_system(record: JsonObject) -> ShipSystem:
    _fields(
        record,
        required=_SOURCE_FIELDS | {"ship_id", "system_code", "name"},
    )
    return ShipSystem(
        id=_uuid(record, "id"),
        source_system=_text(record, "source_system"),
        source_id=_text(record, "source_id"),
        source_updated_at=_datetime(record, "source_updated_at"),
        ship_id=_uuid(record, "ship_id"),
        system_code=_text(record, "system_code"),
        name=_text(record, "name"),
    )


def _drawing(record: JsonObject) -> Drawing:
    _fields(
        record,
        required=_SOURCE_FIELDS | {"ship_id", "drawing_no", "title", "revision"},
        optional={"system_id", "status"},
    )
    return Drawing(
        id=_uuid(record, "id"),
        source_system=_text(record, "source_system"),
        source_id=_text(record, "source_id"),
        source_updated_at=_datetime(record, "source_updated_at"),
        ship_id=_uuid(record, "ship_id"),
        drawing_no=_text(record, "drawing_no"),
        title=_text(record, "title"),
        revision=_text(record, "revision"),
        system_id=_optional_uuid(record, "system_id"),
        status=_optional_text(record, "status"),
    )


def _equipment(record: JsonObject) -> Equipment:
    _fields(
        record,
        required=_SOURCE_FIELDS | {"ship_id", "equipment_code"},
        optional={"system_id", "drawing_id", "manufacturer", "model"},
    )
    return Equipment(
        id=_uuid(record, "id"),
        source_system=_text(record, "source_system"),
        source_id=_text(record, "source_id"),
        source_updated_at=_datetime(record, "source_updated_at"),
        ship_id=_uuid(record, "ship_id"),
        equipment_code=_text(record, "equipment_code"),
        system_id=_optional_uuid(record, "system_id"),
        drawing_id=_optional_uuid(record, "drawing_id"),
        manufacturer=_optional_text(record, "manufacturer"),
        model=_optional_text(record, "model"),
    )


def _material(record: JsonObject) -> Material:
    _fields(
        record,
        required=_SOURCE_FIELDS | {"material_code", "description"},
        optional={"specification", "unit"},
    )
    return Material(
        id=_uuid(record, "id"),
        source_system=_text(record, "source_system"),
        source_id=_text(record, "source_id"),
        source_updated_at=_datetime(record, "source_updated_at"),
        material_code=_text(record, "material_code"),
        description=_text(record, "description"),
        specification=_optional_text(record, "specification"),
        unit=_optional_text(record, "unit"),
    )


def _bom_item(record: JsonObject) -> BOMItem:
    _fields(
        record,
        required=_SOURCE_FIELDS | {"material_id", "quantity"},
        optional={"drawing_id", "equipment_id"},
    )
    return BOMItem(
        id=_uuid(record, "id"),
        source_system=_text(record, "source_system"),
        source_id=_text(record, "source_id"),
        source_updated_at=_datetime(record, "source_updated_at"),
        material_id=_uuid(record, "material_id"),
        quantity=_quantity(record, "quantity"),
        drawing_id=_optional_uuid(record, "drawing_id"),
        equipment_id=_optional_uuid(record, "equipment_id"),
    )


def _supplier(record: JsonObject) -> Supplier:
    _fields(
        record,
        required=_SOURCE_FIELDS | {"supplier_code", "canonical_name"},
    )
    return Supplier(
        id=_uuid(record, "id"),
        source_system=_text(record, "source_system"),
        source_id=_text(record, "source_id"),
        source_updated_at=_datetime(record, "source_updated_at"),
        supplier_code=_text(record, "supplier_code"),
        canonical_name=_text(record, "canonical_name"),
    )


def _purchase_order(record: JsonObject) -> PurchaseOrder:
    _fields(
        record,
        required=_SOURCE_FIELDS | {"ship_id", "supplier_id", "po_number", "status"},
        optional={
            "material_id",
            "equipment_id",
            "quantity",
            "required_date",
            "promised_date",
            "actual_date",
            "criticality",
        },
    )
    return PurchaseOrder(
        id=_uuid(record, "id"),
        source_system=_text(record, "source_system"),
        source_id=_text(record, "source_id"),
        source_updated_at=_datetime(record, "source_updated_at"),
        ship_id=_uuid(record, "ship_id"),
        supplier_id=_uuid(record, "supplier_id"),
        po_number=_text(record, "po_number"),
        status=_text(record, "status"),
        material_id=_optional_uuid(record, "material_id"),
        equipment_id=_optional_uuid(record, "equipment_id"),
        quantity=_optional_quantity(record, "quantity"),
        required_date=_optional_date(record, "required_date"),
        promised_date=_optional_date(record, "promised_date"),
        actual_date=_optional_date(record, "actual_date"),
        criticality=_optional_text(record, "criticality"),
    )


def _project_task(record: JsonObject) -> ProjectTask:
    _fields(
        record,
        required=_SOURCE_FIELDS | {"ship_id", "task_code", "name"},
        optional={
            "planned_start",
            "planned_end",
            "actual_start",
            "actual_end",
            "planned_progress",
            "actual_progress",
            "critical_path",
        },
    )
    return ProjectTask(
        id=_uuid(record, "id"),
        source_system=_text(record, "source_system"),
        source_id=_text(record, "source_id"),
        source_updated_at=_datetime(record, "source_updated_at"),
        ship_id=_uuid(record, "ship_id"),
        task_code=_text(record, "task_code"),
        name=_text(record, "name"),
        planned_start=_optional_date(record, "planned_start"),
        planned_end=_optional_date(record, "planned_end"),
        actual_start=_optional_date(record, "actual_start"),
        actual_end=_optional_date(record, "actual_end"),
        planned_progress=_optional_progress(record, "planned_progress"),
        actual_progress=_optional_progress(record, "actual_progress"),
        critical_path=_optional_bool(record, "critical_path"),
    )


def _alias(record: JsonObject) -> EntityAlias:
    _fields(
        record,
        required={"id", "entity_type", "entity_id", "alias"},
        optional={"source_system"},
    )
    return EntityAlias(
        id=_uuid(record, "id"),
        entity_type=AliasEntityType(_text(record, "entity_type")),
        entity_id=_uuid(record, "entity_id"),
        alias=_text(record, "alias"),
        source_system=_optional_text(record, "source_system"),
    )


def _security_context(record: JsonObject) -> NamedUserContext:
    _fields(
        record,
        required={
            "name",
            "user_id",
            "roles",
            "departments",
            "allowed_ship_ids",
            "allowed_project_ids",
            "security_clearance",
        },
    )
    return NamedUserContext(
        name=_text(record, "name"),
        user_context=UserContext(
            user_id=_text(record, "user_id"),
            roles=frozenset(_text_list(record, "roles")),
            departments=frozenset(_text_list(record, "departments")),
            allowed_ship_ids=frozenset(
                _uuid_text_list(record, "allowed_ship_ids")
            ),
            allowed_project_ids=frozenset(
                _uuid_text_list(record, "allowed_project_ids")
            ),
            security_clearance=SecurityLevel[
                _text(record, "security_clearance")
            ],
        ),
    )


_MANIFEST_FIELDS = frozenset(
    {
        "dataset_id",
        "dataset_version",
        "synthetic",
        "as_of_date",
        "purchase_order_cases",
        "security_scope_ships",
    }
)


def _validate_manifest(record: JsonObject) -> None:
    try:
        _fields(record, required=_MANIFEST_FIELDS)
        if (
            _text(record, "dataset_id") != "synthetic-shipyard-v1"
            or _integer(record, "dataset_version") != 1
            or _boolean(record, "synthetic") is not True
            or _date(record, "as_of_date") != date(2026, 8, 18)
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        _error("manifest.json", "manifest")


def _manifest_dataset_id(record: JsonObject) -> str:
    _validate_manifest(record)
    return _text(record, "dataset_id")


def _manifest_dataset_version(record: JsonObject) -> int:
    return _integer(record, "dataset_version")


def _manifest_as_of_date(record: JsonObject) -> date:
    return _date(record, "as_of_date")


def _manifest_object(record: JsonObject, field: str) -> JsonObject:
    value = record[field]
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise TypeError
    return value


def _purchase_order_cases(record: JsonObject) -> PurchaseOrderCases:
    try:
        value = _manifest_object(record, "purchase_order_cases")
        _fields(
            value,
            required={"overdue_ids", "non_overdue_ids", "delivered_ids"},
        )
        return PurchaseOrderCases(
            overdue_ids=_uuid_list(value, "overdue_ids"),
            non_overdue_ids=_uuid_list(value, "non_overdue_ids"),
            delivered_ids=_uuid_list(value, "delivered_ids"),
        )
    except (KeyError, TypeError, ValueError):
        _error("manifest.json", "manifest")


def _uuid_list(record: JsonObject, field: str) -> frozenset[UUID]:
    values = _text_list(record, field)
    result: set[UUID] = set()
    for value in values:
        parsed = UUID(value)
        if str(parsed) != value:
            raise ValueError
        result.add(parsed)
    if len(result) != len(values):
        raise ValueError
    return frozenset(result)


def _security_scope_ships(record: JsonObject) -> dict[str, UUID]:
    try:
        value = _manifest_object(record, "security_scope_ships")
        _fields(value, required=frozenset(_EXPECTED_SECURITY_SCOPE_SHIPS))
        parsed = {name: _uuid(value, name) for name in value}
        if parsed != _EXPECTED_SECURITY_SCOPE_SHIPS:
            raise ValueError
        return parsed
    except (KeyError, TypeError, ValueError):
        _error("manifest.json", "security scope")


def _validate_fixture_set(
    fixture_set: ShipyardFixtureSet,
    security_scope_ships: dict[str, UUID],
) -> None:
    sourced_groups = (
        ("ships.json", fixture_set.ships),
        ("ship_systems.json", fixture_set.ship_systems),
        ("drawings.json", fixture_set.drawings),
        ("equipment.json", fixture_set.equipment),
        ("materials.json", fixture_set.materials),
        ("bom_items.json", fixture_set.bom_items),
        ("suppliers.json", fixture_set.suppliers),
        ("purchase_orders.json", fixture_set.purchase_orders),
        ("project_tasks.json", fixture_set.project_tasks),
    )

    seen_ids: set[UUID] = set()
    for file_name, group in sourced_groups:
        seen_sources: set[tuple[str, str]] = set()
        for index, record in enumerate(group):
            if (
                record.source_system != "synthetic-fixture"
                or not record.source_id.startswith("synthetic:")
            ):
                _error(file_name, "provenance", index)
            if record.id in seen_ids:
                _error(file_name, "duplicate id", index)
            seen_ids.add(record.id)
            source_key = (record.source_system, record.source_id)
            if source_key in seen_sources:
                _error(file_name, "duplicate source", index)
            seen_sources.add(source_key)

    for index, alias in enumerate(fixture_set.aliases):
        if alias.id in seen_ids:
            _error("aliases.json", "duplicate id", index)
        seen_ids.add(alias.id)

    ships = {ship.id: ship for ship in fixture_set.ships}
    systems = {system.id: system for system in fixture_set.ship_systems}
    drawings = {drawing.id: drawing for drawing in fixture_set.drawings}
    equipment = {item.id: item for item in fixture_set.equipment}
    materials = {material.id: material for material in fixture_set.materials}
    suppliers = {supplier.id: supplier for supplier in fixture_set.suppliers}
    orders = {order.id: order for order in fixture_set.purchase_orders}

    for index, system_record in enumerate(fixture_set.ship_systems):
        if system_record.ship_id not in ships:
            _error("ship_systems.json", "relationship", index)

    for index, drawing_record in enumerate(fixture_set.drawings):
        parent_system = (
            systems.get(drawing_record.system_id)
            if drawing_record.system_id
            else None
        )
        if drawing_record.ship_id not in ships or (
            drawing_record.system_id is not None
            and (
                parent_system is None
                or parent_system.ship_id != drawing_record.ship_id
            )
        ):
            _error("drawings.json", "relationship", index)

    for index, equipment_record in enumerate(fixture_set.equipment):
        parent_system = (
            systems.get(equipment_record.system_id)
            if equipment_record.system_id
            else None
        )
        parent_drawing = (
            drawings.get(equipment_record.drawing_id)
            if equipment_record.drawing_id
            else None
        )
        if (
            equipment_record.ship_id not in ships
            or (
                equipment_record.system_id is not None
                and (
                    parent_system is None
                    or parent_system.ship_id != equipment_record.ship_id
                )
            )
            or (
                equipment_record.drawing_id is not None
                and (
                    parent_drawing is None
                    or parent_drawing.ship_id != equipment_record.ship_id
                )
            )
        ):
            _error("equipment.json", "relationship", index)

    for index, bom_item in enumerate(fixture_set.bom_items):
        parent_drawing = (
            drawings.get(bom_item.drawing_id) if bom_item.drawing_id else None
        )
        parent_equipment = (
            equipment.get(bom_item.equipment_id)
            if bom_item.equipment_id
            else None
        )
        if (
            bom_item.material_id not in materials
            or (bom_item.drawing_id is not None and parent_drawing is None)
            or (bom_item.equipment_id is not None and parent_equipment is None)
            or (
                parent_drawing is not None
                and parent_equipment is not None
                and parent_drawing.ship_id != parent_equipment.ship_id
            )
        ):
            _error("bom_items.json", "relationship", index)

    for index, purchase_order in enumerate(fixture_set.purchase_orders):
        parent_equipment = (
            equipment.get(purchase_order.equipment_id)
            if purchase_order.equipment_id
            else None
        )
        if (
            purchase_order.ship_id not in ships
            or purchase_order.supplier_id not in suppliers
            or (
                purchase_order.material_id is not None
                and purchase_order.material_id not in materials
            )
            or (
                purchase_order.equipment_id is not None
                and parent_equipment is None
            )
            or (
                parent_equipment is not None
                and parent_equipment.ship_id != purchase_order.ship_id
            )
        ):
            _error("purchase_orders.json", "relationship", index)

    for index, task in enumerate(fixture_set.project_tasks):
        if task.ship_id not in ships:
            _error("project_tasks.json", "relationship", index)

    alias_targets = {
        AliasEntityType.SUPPLIER: set(suppliers),
        AliasEntityType.EQUIPMENT: set(equipment),
        AliasEntityType.MATERIAL: set(materials),
    }
    for index, alias in enumerate(fixture_set.aliases):
        if alias.entity_id not in alias_targets[alias.entity_type]:
            _error("aliases.json", "relationship", index)

    _validate_security_scopes(fixture_set, security_scope_ships, set(ships))
    _validate_purchase_order_cases(fixture_set, orders)


def _validate_security_scopes(
    fixture_set: ShipyardFixtureSet,
    security_scope_ships: dict[str, UUID],
    ship_ids: set[UUID],
) -> None:
    contexts = fixture_set.security_contexts
    expected_names = set(_EXPECTED_SECURITY_SCOPE_SHIPS)
    actual_names = {context.name for context in contexts}
    if (
        security_scope_ships != _EXPECTED_SECURITY_SCOPE_SHIPS
        or len(contexts) != len(_EXPECTED_SECURITY_SCOPE_SHIPS)
        or actual_names != expected_names
        or not set(_EXPECTED_SECURITY_SCOPE_SHIPS.values()) <= ship_ids
    ):
        _error("security_scopes.json", "security scope")

    for index, context in enumerate(contexts):
        expected_ship_id = _EXPECTED_SECURITY_SCOPE_SHIPS[context.name]
        if (
            context.user_context.allowed_ship_ids
            != frozenset({str(expected_ship_id)})
            or context.user_context.allowed_project_ids
        ):
            _error("security_scopes.json", "security scope", index)


def _validate_purchase_order_cases(
    fixture_set: ShipyardFixtureSet,
    orders: dict[UUID, PurchaseOrder],
) -> None:
    cases = fixture_set.purchase_order_cases
    if not cases.overdue_ids or not cases.non_overdue_ids or not cases.delivered_ids:
        _error("manifest.json", "purchase-order case")

    for order_id in cases.overdue_ids:
        order = orders.get(order_id)
        if not (
            order is not None
            and order.status == "OPEN"
            and order.actual_date is None
            and order.promised_date is not None
            and order.promised_date < fixture_set.as_of_date
        ):
            _error("manifest.json", "purchase-order case")

    for order_id in cases.non_overdue_ids:
        order = orders.get(order_id)
        if not (
            order is not None
            and order.status == "OPEN"
            and order.actual_date is None
            and order.promised_date is not None
            and order.promised_date >= fixture_set.as_of_date
        ):
            _error("manifest.json", "purchase-order case")

    for order_id in cases.delivered_ids:
        order = orders.get(order_id)
        if not (
            order is not None
            and order.status == "DELIVERED"
            and order.actual_date is not None
        ):
            _error("manifest.json", "purchase-order case")


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
