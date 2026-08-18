"""Authorization-aware exact resolution of canonical entity aliases."""

from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from packages.contracts.auth import AuthorizationScope, UserContext
from packages.domain import AliasEntityType, EntityAlias, Equipment
from services.auth.service import authorization_scope_for


class AliasReader(Protocol):
    """Port required for exact alias lookup."""

    def resolve(
        self,
        entity_type: AliasEntityType,
        raw_alias: str,
        source_system: str | None = None,
    ) -> EntityAlias | None: ...


class EntityResolutionService:
    """Resolve aliases without exposing out-of-scope Equipment existence."""

    def __init__(
        self,
        alias_reader: AliasReader,
        equipment_by_id: Callable[[UUID], Equipment | None],
    ) -> None:
        self._alias_reader = alias_reader
        self._equipment_by_id = equipment_by_id

    def resolve(
        self,
        *,
        entity_type: AliasEntityType,
        raw_alias: str,
        user_context: UserContext,
        source_system: str | None = None,
        requested_scope: AuthorizationScope | None = None,
    ) -> EntityAlias | None:
        scope = authorization_scope_for(user_context, requested_scope)
        if entity_type is AliasEntityType.EQUIPMENT and not scope.allowed_ship_ids:
            return None
        alias = self._alias_reader.resolve(
            entity_type,
            raw_alias,
            source_system,
        )
        if alias is None:
            return None
        if entity_type is not AliasEntityType.EQUIPMENT:
            return alias
        equipment = self._equipment_by_id(alias.entity_id)
        if equipment is None:
            return None
        if str(equipment.ship_id) not in scope.allowed_ship_ids:
            return None
        return alias
