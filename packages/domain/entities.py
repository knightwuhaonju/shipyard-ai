"""Immutable canonical shipyard entities with explicit source provenance."""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from packages.domain.value_objects import (
    DomainValidationError,
    PositiveQuantity,
    Progress,
)


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


def _require_date_range(
    prefix: str,
    start: date | None,
    end: date | None,
) -> None:
    _require_optional_date(f"{prefix}_start", start)
    _require_optional_date(f"{prefix}_end", end)
    if start is not None and end is not None and start > end:
        raise DomainValidationError(f"{prefix}_start cannot be after {prefix}_end")


def _require_optional_quantity(value: object | None) -> None:
    if value is not None and not isinstance(value, PositiveQuantity):
        raise DomainValidationError(
            "quantity must be a PositiveQuantity when provided"
        )


def _require_optional_progress(field: str, value: object | None) -> None:
    if value is not None and not isinstance(value, Progress):
        raise DomainValidationError(f"{field} must be a Progress when provided")


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
            raise DomainValidationError("source_updated_at must be timezone-aware")


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
            raise DomainValidationError("BOMItem requires drawing_id or equipment_id")
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
            raise DomainValidationError("critical_path must be a bool when provided")
