"""Minimal SQLAlchemy repository for immutable canonical domain entities."""

from datetime import datetime
from typing import TypedDict, TypeVar, cast
from uuid import UUID

from sqlalchemy.orm import Session

from infra.postgres.models import (
    BOMItemModel,
    DrawingModel,
    EquipmentModel,
    MaterialModel,
    ProjectTaskModel,
    PurchaseOrderModel,
    ShipModel,
    ShipSystemModel,
    SupplierModel,
    _SourcedModel,
)
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

type DomainEntity = (
    Ship
    | ShipSystem
    | Drawing
    | Equipment
    | Material
    | BOMItem
    | Supplier
    | PurchaseOrder
    | ProjectTask
)

EntityT = TypeVar(
    "EntityT",
    Ship,
    ShipSystem,
    Drawing,
    Equipment,
    Material,
    BOMItem,
    Supplier,
    PurchaseOrder,
    ProjectTask,
)


class UnsupportedDomainEntityError(TypeError):
    """Raised for an entity type outside the Task 005 domain set."""


_MODEL_BY_ENTITY: dict[type[object], type[_SourcedModel]] = {
    Ship: ShipModel,
    ShipSystem: ShipSystemModel,
    Drawing: DrawingModel,
    Equipment: EquipmentModel,
    Material: MaterialModel,
    BOMItem: BOMItemModel,
    Supplier: SupplierModel,
    PurchaseOrder: PurchaseOrderModel,
    ProjectTask: ProjectTaskModel,
}


class _SourceValues(TypedDict):
    id: UUID
    source_system: str
    source_id: str
    source_updated_at: datetime


def _source_values(entity: DomainEntity) -> _SourceValues:
    return {
        "id": entity.id,
        "source_system": entity.source_system,
        "source_id": entity.source_id,
        "source_updated_at": entity.source_updated_at,
    }


def _to_model(entity: DomainEntity) -> _SourcedModel:
    source = _source_values(entity)
    match entity:
        case Ship():
            return ShipModel(
                **source,
                ship_code=entity.ship_code,
                name=entity.name,
                customer_name=entity.customer_name,
                vessel_type=entity.vessel_type,
                planned_delivery_date=entity.planned_delivery_date,
            )
        case ShipSystem():
            return ShipSystemModel(
                **source,
                ship_id=entity.ship_id,
                system_code=entity.system_code,
                name=entity.name,
            )
        case Drawing():
            return DrawingModel(
                **source,
                ship_id=entity.ship_id,
                system_id=entity.system_id,
                drawing_no=entity.drawing_no,
                title=entity.title,
                revision=entity.revision,
                status=entity.status,
            )
        case Equipment():
            return EquipmentModel(
                **source,
                ship_id=entity.ship_id,
                system_id=entity.system_id,
                drawing_id=entity.drawing_id,
                equipment_code=entity.equipment_code,
                manufacturer=entity.manufacturer,
                model=entity.model,
            )
        case Material():
            return MaterialModel(
                **source,
                material_code=entity.material_code,
                description=entity.description,
                specification=entity.specification,
                unit=entity.unit,
            )
        case BOMItem():
            return BOMItemModel(
                **source,
                drawing_id=entity.drawing_id,
                equipment_id=entity.equipment_id,
                material_id=entity.material_id,
                quantity=entity.quantity.value,
            )
        case Supplier():
            return SupplierModel(
                **source,
                supplier_code=entity.supplier_code,
                canonical_name=entity.canonical_name,
            )
        case PurchaseOrder():
            return PurchaseOrderModel(
                **source,
                ship_id=entity.ship_id,
                material_id=entity.material_id,
                equipment_id=entity.equipment_id,
                supplier_id=entity.supplier_id,
                po_number=entity.po_number,
                quantity=(entity.quantity.value if entity.quantity else None),
                required_date=entity.required_date,
                promised_date=entity.promised_date,
                actual_date=entity.actual_date,
                status=entity.status,
                criticality=entity.criticality,
            )
        case ProjectTask():
            return ProjectTaskModel(
                **source,
                ship_id=entity.ship_id,
                task_code=entity.task_code,
                name=entity.name,
                planned_start=entity.planned_start,
                planned_end=entity.planned_end,
                actual_start=entity.actual_start,
                actual_end=entity.actual_end,
                planned_progress=(
                    entity.planned_progress.value
                    if entity.planned_progress
                    else None
                ),
                actual_progress=(
                    entity.actual_progress.value if entity.actual_progress else None
                ),
                critical_path=entity.critical_path,
            )
    raise UnsupportedDomainEntityError("unsupported domain entity type")


def _to_domain(model: _SourcedModel) -> DomainEntity:
    source: _SourceValues = {
        "id": model.id,
        "source_system": model.source_system,
        "source_id": model.source_id,
        "source_updated_at": model.source_updated_at,
    }
    match model:
        case ShipModel():
            return Ship(
                **source,
                ship_code=model.ship_code,
                name=model.name,
                customer_name=model.customer_name,
                vessel_type=model.vessel_type,
                planned_delivery_date=model.planned_delivery_date,
            )
        case ShipSystemModel():
            return ShipSystem(
                **source,
                ship_id=model.ship_id,
                system_code=model.system_code,
                name=model.name,
            )
        case DrawingModel():
            return Drawing(
                **source,
                ship_id=model.ship_id,
                system_id=model.system_id,
                drawing_no=model.drawing_no,
                title=model.title,
                revision=model.revision,
                status=model.status,
            )
        case EquipmentModel():
            return Equipment(
                **source,
                ship_id=model.ship_id,
                system_id=model.system_id,
                drawing_id=model.drawing_id,
                equipment_code=model.equipment_code,
                manufacturer=model.manufacturer,
                model=model.model,
            )
        case MaterialModel():
            return Material(
                **source,
                material_code=model.material_code,
                description=model.description,
                specification=model.specification,
                unit=model.unit,
            )
        case BOMItemModel():
            return BOMItem(
                **source,
                drawing_id=model.drawing_id,
                equipment_id=model.equipment_id,
                material_id=model.material_id,
                quantity=PositiveQuantity(model.quantity),
            )
        case SupplierModel():
            return Supplier(
                **source,
                supplier_code=model.supplier_code,
                canonical_name=model.canonical_name,
            )
        case PurchaseOrderModel():
            return PurchaseOrder(
                **source,
                ship_id=model.ship_id,
                material_id=model.material_id,
                equipment_id=model.equipment_id,
                supplier_id=model.supplier_id,
                po_number=model.po_number,
                quantity=(
                    PositiveQuantity(model.quantity)
                    if model.quantity is not None
                    else None
                ),
                required_date=model.required_date,
                promised_date=model.promised_date,
                actual_date=model.actual_date,
                status=model.status,
                criticality=model.criticality,
            )
        case ProjectTaskModel():
            return ProjectTask(
                **source,
                ship_id=model.ship_id,
                task_code=model.task_code,
                name=model.name,
                planned_start=model.planned_start,
                planned_end=model.planned_end,
                actual_start=model.actual_start,
                actual_end=model.actual_end,
                planned_progress=(
                    Progress(model.planned_progress)
                    if model.planned_progress is not None
                    else None
                ),
                actual_progress=(
                    Progress(model.actual_progress)
                    if model.actual_progress is not None
                    else None
                ),
                critical_path=model.critical_path,
            )
    raise UnsupportedDomainEntityError("unsupported persistence model type")


class DomainRepository:
    """Insert and load immutable domain entities in a caller-owned session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def insert(self, entity: DomainEntity) -> None:
        model = _to_model(entity)
        with self._session.begin_nested():
            self._session.add(model)
            self._session.flush()

    def get(
        self,
        entity_type: type[EntityT],
        entity_id: UUID,
    ) -> EntityT | None:
        model_type = _MODEL_BY_ENTITY.get(entity_type)
        if model_type is None:
            raise UnsupportedDomainEntityError("unsupported domain entity type")
        model = self._session.get(model_type, entity_id)
        if model is None:
            return None
        return cast(EntityT, _to_domain(model))
