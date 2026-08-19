from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import CheckConstraint, Index, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.domain import (
    AliasEntityType,
    EntityAlias,
    Equipment,
    Material,
    Ship,
    Supplier,
)

ALIAS_TABLE = "entity_aliases"
ALIAS_ID = UUID("71000000-0000-0000-0000-000000000001")
SHIP_ID = UUID("71000000-0000-0000-0000-000000000002")
EQUIPMENT_ID = UUID("71000000-0000-0000-0000-000000000003")
MATERIAL_ID = UUID("71000000-0000-0000-0000-000000000004")
SUPPLIER_ID = UUID("71000000-0000-0000-0000-000000000005")
SOURCE_UPDATED_AT = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)


def _ship(entity_id: UUID) -> Ship:
    return Ship(
        id=entity_id,
        source_system="synthetic-source",
        source_id=f"ship-{entity_id}",
        source_updated_at=SOURCE_UPDATED_AT,
        ship_code=f"SHIP-{entity_id}",
    )


def _equipment(entity_id: UUID, ship_id: UUID) -> Equipment:
    return Equipment(
        id=entity_id,
        source_system="synthetic-source",
        source_id=f"equipment-{entity_id}",
        source_updated_at=SOURCE_UPDATED_AT,
        ship_id=ship_id,
        equipment_code=f"EQ-{entity_id}",
    )


def _material(entity_id: UUID, code: str) -> Material:
    return Material(
        id=entity_id,
        source_system="synthetic-source",
        source_id=f"material-{entity_id}",
        source_updated_at=SOURCE_UPDATED_AT,
        material_code=code,
        description=f"Synthetic material {code}",
    )


def _supplier(entity_id: UUID, source_id: str, code: str, name: str) -> Supplier:
    return Supplier(
        id=entity_id,
        source_system="synthetic-source",
        source_id=source_id,
        source_updated_at=SOURCE_UPDATED_AT,
        supplier_code=code,
        canonical_name=name,
    )


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
            == "20260819_0003"
        )


def test_three_explicit_supplier_aliases_resolve_to_one_canonical_supplier(
    migrated_session: Session,
) -> None:
    from infra.postgres import AliasRepository, DomainRepository

    supplier = _supplier(SUPPLIER_ID, "supplier-001", "SUP-001", "Wärtsilä")
    DomainRepository(migrated_session).insert(supplier)
    repository = AliasRepository(migrated_session)
    aliases = [
        EntityAlias(
            id=UUID("72000000-0000-0000-0000-000000000001"),
            entity_type=AliasEntityType.SUPPLIER,
            entity_id=supplier.id,
            alias="Wärtsilä",
        ),
        EntityAlias(
            id=UUID("72000000-0000-0000-0000-000000000002"),
            entity_type=AliasEntityType.SUPPLIER,
            entity_id=supplier.id,
            alias="Wartsila",
        ),
        EntityAlias(
            id=UUID("72000000-0000-0000-0000-000000000003"),
            entity_type=AliasEntityType.SUPPLIER,
            entity_id=supplier.id,
            alias="瓦锡兰",
        ),
    ]
    for alias in aliases:
        repository.insert(alias)
    migrated_session.commit()
    migrated_session.expunge_all()

    assert repository.resolve(AliasEntityType.SUPPLIER, "WÄRTSILÄ") == aliases[0]
    assert repository.resolve(AliasEntityType.SUPPLIER, "Wartsila") == aliases[1]
    assert repository.resolve(AliasEntityType.SUPPLIER, "瓦锡兰") == aliases[2]
    assert repository.resolve(AliasEntityType.SUPPLIER, "Wartsilla") is None


def test_source_specific_alias_precedes_global_without_crossing_sources(
    migrated_session: Session,
) -> None:
    from infra.postgres import AliasRepository, DomainRepository

    material_a = _material(MATERIAL_ID, "MAT-A")
    material_b = _material(UUID("71000000-0000-0000-0000-000000000006"), "MAT-B")
    domain_repository = DomainRepository(migrated_session)
    domain_repository.insert(material_a)
    domain_repository.insert(material_b)
    repository = AliasRepository(migrated_session)
    global_alias = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000004"),
        entity_type=AliasEntityType.MATERIAL,
        entity_id=material_a.id,
        alias="Shared code",
    )
    source_alias = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000005"),
        entity_type=AliasEntityType.MATERIAL,
        entity_id=material_b.id,
        alias="Shared code",
        source_system="erp-a",
    )
    source_only_alias = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000010"),
        entity_type=AliasEntityType.MATERIAL,
        entity_id=material_b.id,
        alias="Source only code",
        source_system="erp-a",
    )
    repository.insert(global_alias)
    repository.insert(source_alias)
    repository.insert(source_only_alias)
    migrated_session.commit()

    assert repository.resolve(AliasEntityType.MATERIAL, "shared code") == global_alias
    assert (
        repository.resolve(AliasEntityType.MATERIAL, "shared code", "erp-a")
        == source_alias
    )
    assert (
        repository.resolve(AliasEntityType.MATERIAL, "shared code", "erp-b")
        == global_alias
    )
    assert repository.resolve(AliasEntityType.MATERIAL, "source only code") is None
    assert (
        repository.resolve(AliasEntityType.MATERIAL, "source only code", "erp-b")
        is None
    )


@pytest.mark.parametrize(
    ("entity_type", "entity_id", "raw_alias"),
    [
        (AliasEntityType.SUPPLIER, SUPPLIER_ID, "supplier alias"),
        (AliasEntityType.EQUIPMENT, EQUIPMENT_ID, "equipment alias"),
        (AliasEntityType.MATERIAL, MATERIAL_ID, "material alias"),
    ],
)
def test_alias_round_trip_preserves_typed_target(
    migrated_session: Session,
    entity_type: AliasEntityType,
    entity_id: UUID,
    raw_alias: str,
) -> None:
    from infra.postgres import AliasRepository, DomainRepository

    ship = _ship(SHIP_ID)
    domain_repository = DomainRepository(migrated_session)
    for entity in (
        ship,
        _equipment(EQUIPMENT_ID, ship.id),
        _material(MATERIAL_ID, "MAT-ROUNDTRIP"),
        _supplier(SUPPLIER_ID, "supplier-roundtrip", "SUP-ROUNDTRIP", "Supplier"),
    ):
        domain_repository.insert(entity)
    alias = EntityAlias(
        id=ALIAS_ID,
        entity_type=entity_type,
        entity_id=entity_id,
        alias=raw_alias,
    )
    repository = AliasRepository(migrated_session)
    repository.insert(alias)
    migrated_session.commit()

    loaded = repository.resolve(entity_type, raw_alias)
    assert loaded is not None
    assert loaded.entity_type is entity_type
    assert loaded.entity_id == entity_id


def test_missing_target_uses_safe_error_and_preserves_session(
    migrated_session: Session,
) -> None:
    from infra.postgres import (
        AliasPersistenceError,
        AliasRepository,
        DomainRepository,
    )

    sensitive_alias = "missing-sensitive-alias"
    missing_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    repository = AliasRepository(migrated_session)
    missing = EntityAlias(
        id=ALIAS_ID,
        entity_type=AliasEntityType.SUPPLIER,
        entity_id=missing_id,
        alias=sensitive_alias,
    )
    with pytest.raises(AliasPersistenceError) as captured:
        repository.insert(missing)

    assert str(captured.value) == "entity alias violates persistence constraints"
    assert sensitive_alias not in str(captured.value)
    assert str(missing_id) not in str(captured.value)

    supplier = _supplier(SUPPLIER_ID, "supplier-recovery", "SUP-R", "Recovered")
    DomainRepository(migrated_session).insert(supplier)
    valid = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000006"),
        entity_type=AliasEntityType.SUPPLIER,
        entity_id=supplier.id,
        alias="valid-after-rejection",
    )
    repository.insert(valid)
    assert repository.resolve(AliasEntityType.SUPPLIER, valid.alias) == valid


def test_alias_collision_does_not_reassign_and_entity_types_are_independent(
    migrated_session: Session,
) -> None:
    from infra.postgres import (
        AliasPersistenceError,
        AliasRepository,
        DomainRepository,
    )

    supplier = _supplier(SUPPLIER_ID, "supplier-collision", "SUP-C", "Supplier")
    material = _material(MATERIAL_ID, "MAT-C")
    domain_repository = DomainRepository(migrated_session)
    domain_repository.insert(supplier)
    domain_repository.insert(material)
    repository = AliasRepository(migrated_session)
    first = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000007"),
        entity_type=AliasEntityType.SUPPLIER,
        entity_id=supplier.id,
        alias=" Shared  Code ",
    )
    duplicate = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000008"),
        entity_type=AliasEntityType.SUPPLIER,
        entity_id=supplier.id,
        alias="shared code",
    )
    material_alias = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000009"),
        entity_type=AliasEntityType.MATERIAL,
        entity_id=material.id,
        alias="shared code",
    )
    repository.insert(first)
    with pytest.raises(
        AliasPersistenceError,
        match="^entity alias violates persistence constraints$",
    ):
        repository.insert(duplicate)
    repository.insert(material_alias)

    assert repository.resolve(AliasEntityType.SUPPLIER, "shared code") == first
    assert (
        repository.resolve(AliasEntityType.MATERIAL, "shared code") == material_alias
    )


def test_source_specific_collision_is_rejected_only_within_exact_source(
    migrated_session: Session,
) -> None:
    from infra.postgres import (
        AliasPersistenceError,
        AliasRepository,
        DomainRepository,
    )

    supplier = _supplier(SUPPLIER_ID, "supplier-source", "SUP-S", "Supplier")
    DomainRepository(migrated_session).insert(supplier)
    repository = AliasRepository(migrated_session)
    first = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000011"),
        entity_type=AliasEntityType.SUPPLIER,
        entity_id=supplier.id,
        alias="Source code",
        source_system="erp-a",
    )
    duplicate_same_source = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000012"),
        entity_type=AliasEntityType.SUPPLIER,
        entity_id=supplier.id,
        alias=" source  code ",
        source_system="erp-a",
    )
    other_source = EntityAlias(
        id=UUID("72000000-0000-0000-0000-000000000013"),
        entity_type=AliasEntityType.SUPPLIER,
        entity_id=supplier.id,
        alias="source code",
        source_system="erp-b",
    )
    repository.insert(first)
    with pytest.raises(
        AliasPersistenceError,
        match="^entity alias violates persistence constraints$",
    ):
        repository.insert(duplicate_same_source)
    repository.insert(other_source)

    assert (
        repository.resolve(AliasEntityType.SUPPLIER, "source code", "erp-a")
        == first
    )
    assert (
        repository.resolve(AliasEntityType.SUPPLIER, "source code", "erp-b")
        == other_source
    )


def test_database_rejects_entity_type_and_typed_target_mismatch(
    migrated_session: Session,
) -> None:
    from infra.postgres import DomainRepository
    from infra.postgres.models import EntityAliasModel

    ship = _ship(SHIP_ID)
    equipment = _equipment(EQUIPMENT_ID, ship.id)
    domain_repository = DomainRepository(migrated_session)
    domain_repository.insert(ship)
    domain_repository.insert(equipment)
    migrated_session.flush()

    with pytest.raises(IntegrityError), migrated_session.begin_nested():
        migrated_session.add(
            EntityAliasModel(
                id=ALIAS_ID,
                entity_type="supplier",
                alias="wrong target",
                normalized_alias="wrong target",
                source_system=None,
                supplier_id=None,
                equipment_id=equipment.id,
                material_id=None,
            )
        )
        migrated_session.flush()


def test_corrupt_stored_alias_with_multiple_typed_targets_uses_safe_error() -> None:
    from infra.postgres import AliasPersistenceError
    from infra.postgres.alias_repository import _to_domain
    from infra.postgres.models import EntityAliasModel

    sensitive_alias = "corrupt-sensitive-alias"
    corrupted = EntityAliasModel(
        id=ALIAS_ID,
        entity_type="supplier",
        alias=sensitive_alias,
        normalized_alias=sensitive_alias,
        source_system=None,
        supplier_id=SUPPLIER_ID,
        equipment_id=EQUIPMENT_ID,
        material_id=None,
    )

    with pytest.raises(AliasPersistenceError) as captured:
        _to_domain(corrupted)

    assert str(captured.value) == "stored entity alias is invalid"
    assert sensitive_alias not in str(captured.value)
    assert str(SUPPLIER_ID) not in str(captured.value)
    assert str(EQUIPMENT_ID) not in str(captured.value)


def test_resolve_rejects_blank_source_system_without_value_leak(
    migrated_session: Session,
) -> None:
    from infra.postgres import AliasRepository
    from packages.domain import DomainValidationError

    with pytest.raises(DomainValidationError) as captured:
        AliasRepository(migrated_session).resolve(
            AliasEntityType.SUPPLIER,
            "safe alias",
            "   ",
        )

    assert str(captured.value) == "source_system must be non-blank when provided"
