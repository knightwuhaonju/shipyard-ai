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
