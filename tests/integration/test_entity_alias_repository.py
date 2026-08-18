from uuid import UUID

from sqlalchemy import CheckConstraint, Index, inspect, text
from sqlalchemy.engine import Engine

ALIAS_TABLE = "entity_aliases"
ALIAS_ID = UUID("71000000-0000-0000-0000-000000000001")
SHIP_ID = UUID("71000000-0000-0000-0000-000000000002")
EQUIPMENT_ID = UUID("71000000-0000-0000-0000-000000000003")
MATERIAL_ID = UUID("71000000-0000-0000-0000-000000000004")
SUPPLIER_ID = UUID("71000000-0000-0000-0000-000000000005")


def test_alias_metadata_declares_typed_targets_and_lookup_constraints() -> None:
    from infra.postgres.models import Base

    table = Base.metadata.tables[ALIAS_TABLE]
    assert {
        "id",
        "entity_type",
        "alias",
        "normalized_alias",
        "source_system",
        "supplier_id",
        "equipment_id",
        "material_id",
    } == {column.name for column in table.columns}
    assert {
        column.name: next(iter(column.foreign_keys)).target_fullname
        for column in table.columns
        if column.foreign_keys
    } == {
        "supplier_id": "suppliers.id",
        "equipment_id": "equipment.id",
        "material_id": "materials.id",
    }
    check_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_entity_aliases_alias",
        "ck_entity_aliases_normalized_alias",
        "ck_entity_aliases_source_system",
        "ck_entity_aliases_target",
    } <= check_names
    assert {index.name for index in table.indexes if isinstance(index, Index)} >= {
        "uq_entity_aliases_global_lookup",
        "uq_entity_aliases_source_lookup",
        "ix_entity_aliases_supplier_id",
        "ix_entity_aliases_equipment_id",
        "ix_entity_aliases_material_id",
    }


def test_alias_migration_is_current_head(migrated_engine: Engine) -> None:
    assert ALIAS_TABLE in inspect(migrated_engine).get_table_names()
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == "20260818_0002"
        )
