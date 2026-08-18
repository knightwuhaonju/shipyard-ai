from datetime import UTC, datetime
from uuid import UUID

import pytest

from packages.contracts.auth import AuthorizationScope, UserContext
from packages.domain import AliasEntityType, EntityAlias, Equipment, normalize_alias
from services.entity_resolution import EntityResolutionService

SHIP_ID = UUID("73000000-0000-0000-0000-000000000001")
EQUIPMENT_ID = UUID("73000000-0000-0000-0000-000000000002")
ALIAS_ID = UUID("73000000-0000-0000-0000-000000000003")


class _Reader:
    def __init__(self, alias: EntityAlias) -> None:
        self.alias = alias

    def resolve(
        self,
        entity_type: AliasEntityType,
        raw_alias: str,
        source_system: str | None = None,
    ) -> EntityAlias | None:
        if (
            entity_type is self.alias.entity_type
            and normalize_alias(raw_alias) == self.alias.normalized_alias
            and source_system == self.alias.source_system
        ):
            return self.alias
        return None


def _service_fixture() -> tuple[
    EntityResolutionService,
    EntityAlias,
    Equipment,
]:
    equipment = Equipment(
        id=EQUIPMENT_ID,
        source_system="synthetic-source",
        source_id="equipment-scope",
        source_updated_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
        ship_id=SHIP_ID,
        equipment_code="EQ-SCOPE",
    )
    alias = EntityAlias(
        id=ALIAS_ID,
        entity_type=AliasEntityType.EQUIPMENT,
        entity_id=equipment.id,
        alias="Main Cooling Pump",
    )
    return (
        EntityResolutionService(
            _Reader(alias),
            lambda entity_id: equipment if entity_id == equipment.id else None,
        ),
        alias,
        equipment,
    )


def test_equipment_alias_resolves_inside_allowed_ship_scope() -> None:
    service, alias, equipment = _service_fixture()
    context = UserContext(
        user_id="allowed-user",
        allowed_ship_ids={str(equipment.ship_id)},
    )

    assert service.resolve(
        entity_type=AliasEntityType.EQUIPMENT,
        raw_alias=alias.alias,
        user_context=context,
    ) == alias


@pytest.mark.parametrize(
    "allowed_ship_ids",
    [set(), {"72000000-0000-0000-0000-ffffffffffff"}],
)
def test_equipment_alias_does_not_leak_across_ship_scope(
    allowed_ship_ids: set[str],
) -> None:
    service, alias, _ = _service_fixture()
    context = UserContext(
        user_id="out-of-scope-user",
        allowed_ship_ids=allowed_ship_ids,
    )

    assert service.resolve(
        entity_type=AliasEntityType.EQUIPMENT,
        raw_alias=alias.alias,
        user_context=context,
    ) is None


def test_requested_scope_can_narrow_but_not_widen_equipment_access() -> None:
    service, alias, equipment = _service_fixture()
    context = UserContext(
        user_id="authenticated-user",
        allowed_ship_ids={str(equipment.ship_id)},
    )
    narrowed = AuthorizationScope(allowed_ship_ids=set())

    assert service.resolve(
        entity_type=AliasEntityType.EQUIPMENT,
        raw_alias=alias.alias,
        user_context=context,
        requested_scope=narrowed,
    ) is None


def test_missing_canonical_equipment_is_indistinguishable_from_denial() -> None:
    _, alias, equipment = _service_fixture()
    service = EntityResolutionService(_Reader(alias), lambda _: None)
    context = UserContext(
        user_id="allowed-user",
        allowed_ship_ids={str(equipment.ship_id)},
    )

    assert service.resolve(
        entity_type=AliasEntityType.EQUIPMENT,
        raw_alias=alias.alias,
        user_context=context,
    ) is None
