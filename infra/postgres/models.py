"""SQLAlchemy persistence models for the canonical shipyard domain."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import Constraint


class Base(DeclarativeBase):
    """Declarative metadata root for PostgreSQL infrastructure."""


def _source_constraints(table: str) -> tuple[Constraint, ...]:
    return (
        UniqueConstraint(
            "source_system",
            "source_id",
            name=f"uq_{table}_source_identity",
        ),
        CheckConstraint(
            "btrim(source_system) <> ''",
            name=f"ck_{table}_source_system_non_blank",
        ),
        CheckConstraint(
            "btrim(source_id) <> ''",
            name=f"ck_{table}_source_id_non_blank",
        ),
    )


class _SourcedModel:
    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ShipModel(_SourcedModel, Base):
    __tablename__ = "ships"
    __table_args__ = (
        *_source_constraints(__tablename__),
        UniqueConstraint("ship_code", name="uq_ships_ship_code"),
        CheckConstraint("btrim(ship_code) <> ''", name="ck_ships_ship_code"),
        CheckConstraint(
            "name IS NULL OR btrim(name) <> ''", name="ck_ships_name"
        ),
        CheckConstraint(
            "customer_name IS NULL OR btrim(customer_name) <> ''",
            name="ck_ships_customer_name",
        ),
        CheckConstraint(
            "vessel_type IS NULL OR btrim(vessel_type) <> ''",
            name="ck_ships_vessel_type",
        ),
    )

    ship_code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    customer_name: Mapped[str | None] = mapped_column(Text)
    vessel_type: Mapped[str | None] = mapped_column(Text)
    planned_delivery_date: Mapped[date | None] = mapped_column(Date)


class ShipSystemModel(_SourcedModel, Base):
    __tablename__ = "ship_systems"
    __table_args__ = (
        *_source_constraints(__tablename__),
        CheckConstraint(
            "btrim(system_code) <> ''", name="ck_ship_systems_system_code"
        ),
        CheckConstraint("btrim(name) <> ''", name="ck_ship_systems_name"),
    )

    ship_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ships.id", name="fk_ship_systems_ship_id"),
        nullable=False,
        index=True,
    )
    system_code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class DrawingModel(_SourcedModel, Base):
    __tablename__ = "drawings"
    __table_args__ = (
        *_source_constraints(__tablename__),
        CheckConstraint(
            "btrim(drawing_no) <> ''", name="ck_drawings_drawing_no"
        ),
        CheckConstraint("btrim(title) <> ''", name="ck_drawings_title"),
        CheckConstraint("btrim(revision) <> ''", name="ck_drawings_revision"),
        CheckConstraint(
            "status IS NULL OR btrim(status) <> ''", name="ck_drawings_status"
        ),
    )

    ship_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ships.id", name="fk_drawings_ship_id"),
        nullable=False,
        index=True,
    )
    system_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ship_systems.id", name="fk_drawings_system_id"),
        index=True,
    )
    drawing_no: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str | None] = mapped_column(Text)


class EquipmentModel(_SourcedModel, Base):
    __tablename__ = "equipment"
    __table_args__ = (
        *_source_constraints(__tablename__),
        CheckConstraint(
            "btrim(equipment_code) <> ''", name="ck_equipment_equipment_code"
        ),
        CheckConstraint(
            "manufacturer IS NULL OR btrim(manufacturer) <> ''",
            name="ck_equipment_manufacturer",
        ),
        CheckConstraint(
            "model IS NULL OR btrim(model) <> ''", name="ck_equipment_model"
        ),
    )

    ship_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ships.id", name="fk_equipment_ship_id"),
        nullable=False,
        index=True,
    )
    system_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ship_systems.id", name="fk_equipment_system_id"),
        index=True,
    )
    drawing_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("drawings.id", name="fk_equipment_drawing_id"),
        index=True,
    )
    equipment_code: Mapped[str] = mapped_column(Text, nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)


class MaterialModel(_SourcedModel, Base):
    __tablename__ = "materials"
    __table_args__ = (
        *_source_constraints(__tablename__),
        CheckConstraint(
            "btrim(material_code) <> ''", name="ck_materials_material_code"
        ),
        CheckConstraint(
            "btrim(description) <> ''", name="ck_materials_description"
        ),
        CheckConstraint(
            "specification IS NULL OR btrim(specification) <> ''",
            name="ck_materials_specification",
        ),
        CheckConstraint(
            "unit IS NULL OR btrim(unit) <> ''", name="ck_materials_unit"
        ),
    )

    material_code: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    specification: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text)


class BOMItemModel(_SourcedModel, Base):
    __tablename__ = "bom_items"
    __table_args__ = (
        *_source_constraints(__tablename__),
        CheckConstraint(
            "drawing_id IS NOT NULL OR equipment_id IS NOT NULL",
            name="ck_bom_items_target",
        ),
        CheckConstraint(
            "quantity > 0 AND quantity < 'Infinity'::numeric",
            name="ck_bom_items_quantity",
        ),
    )

    drawing_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("drawings.id", name="fk_bom_items_drawing_id"),
        index=True,
    )
    equipment_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("equipment.id", name="fk_bom_items_equipment_id"),
        index=True,
    )
    material_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("materials.id", name="fk_bom_items_material_id"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)


class SupplierModel(_SourcedModel, Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        *_source_constraints(__tablename__),
        CheckConstraint(
            "btrim(supplier_code) <> ''", name="ck_suppliers_supplier_code"
        ),
        CheckConstraint(
            "btrim(canonical_name) <> ''", name="ck_suppliers_canonical_name"
        ),
    )

    supplier_code: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)


class PurchaseOrderModel(_SourcedModel, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        *_source_constraints(__tablename__),
        CheckConstraint(
            "material_id IS NOT NULL OR equipment_id IS NOT NULL",
            name="ck_purchase_orders_target",
        ),
        CheckConstraint(
            "quantity IS NULL OR "
            "(quantity > 0 AND quantity < 'Infinity'::numeric)",
            name="ck_purchase_orders_quantity",
        ),
        CheckConstraint(
            "btrim(po_number) <> ''", name="ck_purchase_orders_po_number"
        ),
        CheckConstraint(
            "btrim(status) <> ''", name="ck_purchase_orders_status"
        ),
        CheckConstraint(
            "criticality IS NULL OR btrim(criticality) <> ''",
            name="ck_purchase_orders_criticality",
        ),
    )

    ship_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ships.id", name="fk_purchase_orders_ship_id"),
        nullable=False,
        index=True,
    )
    material_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("materials.id", name="fk_purchase_orders_material_id"),
        index=True,
    )
    equipment_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("equipment.id", name="fk_purchase_orders_equipment_id"),
        index=True,
    )
    supplier_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("suppliers.id", name="fk_purchase_orders_supplier_id"),
        nullable=False,
        index=True,
    )
    po_number: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    required_date: Mapped[date | None] = mapped_column(Date)
    promised_date: Mapped[date | None] = mapped_column(Date)
    actual_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    criticality: Mapped[str | None] = mapped_column(Text)


class ProjectTaskModel(_SourcedModel, Base):
    __tablename__ = "project_tasks"
    __table_args__ = (
        *_source_constraints(__tablename__),
        CheckConstraint(
            "btrim(task_code) <> ''", name="ck_project_tasks_task_code"
        ),
        CheckConstraint("btrim(name) <> ''", name="ck_project_tasks_name"),
        CheckConstraint(
            "planned_start IS NULL OR planned_end IS NULL "
            "OR planned_start <= planned_end",
            name="ck_project_tasks_planned_dates",
        ),
        CheckConstraint(
            "actual_start IS NULL OR actual_end IS NULL "
            "OR actual_start <= actual_end",
            name="ck_project_tasks_actual_dates",
        ),
        CheckConstraint(
            "planned_progress IS NULL OR "
            "(planned_progress >= 0 AND planned_progress <= 1)",
            name="ck_project_tasks_planned_progress",
        ),
        CheckConstraint(
            "actual_progress IS NULL OR "
            "(actual_progress >= 0 AND actual_progress <= 1)",
            name="ck_project_tasks_actual_progress",
        ),
    )

    ship_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ships.id", name="fk_project_tasks_ship_id"),
        nullable=False,
        index=True,
    )
    task_code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    planned_start: Mapped[date | None] = mapped_column(Date)
    planned_end: Mapped[date | None] = mapped_column(Date)
    actual_start: Mapped[date | None] = mapped_column(Date)
    actual_end: Mapped[date | None] = mapped_column(Date)
    planned_progress: Mapped[Decimal | None] = mapped_column(Numeric)
    actual_progress: Mapped[Decimal | None] = mapped_column(Numeric)
    critical_path: Mapped[bool | None] = mapped_column(Boolean)
