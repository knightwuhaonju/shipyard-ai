from __future__ import annotations

from sqlalchemy import CheckConstraint, DateTime, UniqueConstraint

DOMAIN_TABLES = {
    "bom_items",
    "drawings",
    "equipment",
    "materials",
    "project_tasks",
    "purchase_orders",
    "ship_systems",
    "ships",
    "suppliers",
}


def test_domain_metadata_declares_all_entity_tables_and_source_fields() -> None:
    from infra.postgres.models import Base

    assert set(Base.metadata.tables) == DOMAIN_TABLES
    for table in Base.metadata.tables.values():
        assert {"id", "source_system", "source_id", "source_updated_at"} <= {
            column.name for column in table.columns
        }
        assert table.c.id.primary_key
        assert not table.c.source_system.nullable
        assert not table.c.source_id.nullable
        assert not table.c.source_updated_at.nullable
        assert isinstance(table.c.source_updated_at.type, DateTime)
        assert table.c.source_updated_at.type.timezone is True
        assert any(
            isinstance(constraint, UniqueConstraint)
            and {column.name for column in constraint.columns}
            == {"source_system", "source_id"}
            for constraint in table.constraints
        )


def test_domain_metadata_matches_documented_foreign_keys() -> None:
    from infra.postgres.models import Base

    expected = {
        "ship_systems": {"ship_id": "ships.id"},
        "drawings": {"ship_id": "ships.id", "system_id": "ship_systems.id"},
        "equipment": {
            "ship_id": "ships.id",
            "system_id": "ship_systems.id",
            "drawing_id": "drawings.id",
        },
        "bom_items": {
            "drawing_id": "drawings.id",
            "equipment_id": "equipment.id",
            "material_id": "materials.id",
        },
        "purchase_orders": {
            "ship_id": "ships.id",
            "material_id": "materials.id",
            "equipment_id": "equipment.id",
            "supplier_id": "suppliers.id",
        },
        "project_tasks": {"ship_id": "ships.id"},
    }

    for table_name, expected_targets in expected.items():
        table = Base.metadata.tables[table_name]
        actual_targets = {
            column.name: next(iter(column.foreign_keys)).target_fullname
            for column in table.columns
            if column.foreign_keys
        }
        assert actual_targets == expected_targets


def test_domain_metadata_names_every_database_check() -> None:
    from infra.postgres.models import Base

    required_checks = {
        "bom_items": {"ck_bom_items_target", "ck_bom_items_quantity"},
        "project_tasks": {
            "ck_project_tasks_planned_dates",
            "ck_project_tasks_actual_dates",
            "ck_project_tasks_planned_progress",
            "ck_project_tasks_actual_progress",
        },
        "purchase_orders": {
            "ck_purchase_orders_target",
            "ck_purchase_orders_quantity",
        },
    }

    for table_name, names in required_checks.items():
        table = Base.metadata.tables[table_name]
        actual = {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert names <= actual
