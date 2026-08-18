"""Exact PostgreSQL persistence for explicit canonical entity aliases."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from infra.postgres.models import EntityAliasModel
from packages.domain import (
    AliasEntityType,
    DomainValidationError,
    EntityAlias,
    normalize_alias,
)


class AliasPersistenceError(RuntimeError):
    """Raised when an explicit alias violates persistence constraints."""


def _to_model(alias: EntityAlias) -> EntityAliasModel:
    return EntityAliasModel(
        id=alias.id,
        entity_type=alias.entity_type.value,
        alias=alias.alias,
        normalized_alias=alias.normalized_alias,
        source_system=alias.source_system,
        supplier_id=(
            alias.entity_id
            if alias.entity_type is AliasEntityType.SUPPLIER
            else None
        ),
        equipment_id=(
            alias.entity_id
            if alias.entity_type is AliasEntityType.EQUIPMENT
            else None
        ),
        material_id=(
            alias.entity_id
            if alias.entity_type is AliasEntityType.MATERIAL
            else None
        ),
    )


def _to_domain(model: EntityAliasModel) -> EntityAlias:
    try:
        entity_type = AliasEntityType(model.entity_type)
    except ValueError:
        raise AliasPersistenceError("stored entity alias is invalid") from None
    entity_id, non_target_ids = {
        AliasEntityType.SUPPLIER: (
            model.supplier_id,
            (model.equipment_id, model.material_id),
        ),
        AliasEntityType.EQUIPMENT: (
            model.equipment_id,
            (model.supplier_id, model.material_id),
        ),
        AliasEntityType.MATERIAL: (
            model.material_id,
            (model.supplier_id, model.equipment_id),
        ),
    }[entity_type]
    if entity_id is None or any(value is not None for value in non_target_ids):
        raise AliasPersistenceError("stored entity alias is invalid")
    try:
        alias = EntityAlias(
            id=model.id,
            entity_type=entity_type,
            entity_id=entity_id,
            alias=model.alias,
            source_system=model.source_system,
        )
    except DomainValidationError:
        raise AliasPersistenceError("stored entity alias is invalid") from None
    if alias.normalized_alias != model.normalized_alias:
        raise AliasPersistenceError("stored entity alias is invalid")
    return alias


def _validated_source_system(value: str | None) -> str | None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise DomainValidationError("source_system must be non-blank when provided")
    return value


class AliasRepository:
    """Insert and exactly resolve aliases in a caller-owned Session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def insert(self, alias: EntityAlias) -> None:
        try:
            with self._session.begin_nested():
                self._session.add(_to_model(alias))
                self._session.flush()
        except IntegrityError:
            raise AliasPersistenceError(
                "entity alias violates persistence constraints"
            ) from None

    def resolve(
        self,
        entity_type: AliasEntityType,
        raw_alias: str,
        source_system: str | None = None,
    ) -> EntityAlias | None:
        normalized_alias = normalize_alias(raw_alias)
        source_system = _validated_source_system(source_system)
        base = select(EntityAliasModel).where(
            EntityAliasModel.entity_type == entity_type.value,
            EntityAliasModel.normalized_alias == normalized_alias,
        )
        if source_system is not None:
            source_match = self._session.scalar(
                base.where(EntityAliasModel.source_system == source_system)
            )
            if source_match is not None:
                return _to_domain(source_match)
        global_match = self._session.scalar(
            base.where(EntityAliasModel.source_system.is_(None))
        )
        return _to_domain(global_match) if global_match is not None else None
