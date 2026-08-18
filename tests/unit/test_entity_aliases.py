from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from packages.domain import (
    AliasEntityType,
    DomainValidationError,
    EntityAlias,
    normalize_alias,
)

ALIAS_ID = UUID("70000000-0000-0000-0000-000000000001")
SUPPLIER_ID = UUID("70000000-0000-0000-0000-000000000002")


class _FakeAliasReader:
    def __init__(self, aliases: list[EntityAlias]) -> None:
        self.aliases = aliases
        self.calls: list[tuple[AliasEntityType, str, str | None]] = []

    def resolve(
        self,
        entity_type: AliasEntityType,
        raw_alias: str,
        source_system: str | None = None,
    ) -> EntityAlias | None:
        self.calls.append((entity_type, raw_alias, source_system))
        key = normalize_alias(raw_alias)
        source_matches = [
            alias
            for alias in self.aliases
            if alias.entity_type is entity_type
            and alias.normalized_alias == key
            and alias.source_system == source_system
        ]
        if source_system is not None and source_matches:
            return source_matches[0]
        return next(
            (
                alias
                for alias in self.aliases
                if alias.entity_type is entity_type
                and alias.normalized_alias == key
                and alias.source_system is None
            ),
            None,
        )


def test_explicit_brand_variants_keep_distinct_normalized_keys() -> None:
    from packages.domain.aliases import normalize_alias

    assert normalize_alias("Wärtsilä") == "wärtsilä"
    assert normalize_alias("Wartsila") == "wartsila"
    assert normalize_alias("瓦锡兰") == "瓦锡兰"
    assert (
        len(
            {
                normalize_alias("Wärtsilä"),
                normalize_alias("Wartsila"),
                normalize_alias("瓦锡兰"),
            }
        )
        == 3
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  WARTSILA  ", "wartsila"),
        ("ＷＡＲＴＳＩＬＡ", "wartsila"),
        ("Main\t Cooling\n Pump", "main cooling pump"),
    ],
)
def test_normalize_alias_handles_case_width_and_whitespace(
    raw: str, expected: str
) -> None:
    from packages.domain.aliases import normalize_alias

    assert normalize_alias(raw) == expected


@pytest.mark.parametrize("value", ["", "  \t\n  ", 123])
def test_normalize_alias_rejects_blank_or_non_text_without_value_leak(
    value: object,
) -> None:
    from packages.domain.aliases import normalize_alias

    with pytest.raises(DomainValidationError) as captured:
        normalize_alias(value)  # type: ignore[arg-type]
    assert str(captured.value) == "alias must be non-blank text"
    assert repr(value) not in str(captured.value)


def test_entity_alias_is_frozen_and_computes_its_normalized_key() -> None:
    from packages.domain.aliases import AliasEntityType, EntityAlias

    alias = EntityAlias(
        id=ALIAS_ID,
        entity_type=AliasEntityType.SUPPLIER,
        entity_id=SUPPLIER_ID,
        alias="  Wärtsilä  ",
        source_system="erp-a",
    )
    assert alias.normalized_alias == "wärtsilä"
    with pytest.raises(FrozenInstanceError):
        alias.alias = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "not-a-uuid"},
        {"entity_id": "not-a-uuid"},
        {"entity_type": "supplier"},
        {"source_system": "   "},
    ],
)
def test_entity_alias_rejects_invalid_fields(overrides: dict[str, object]) -> None:
    from packages.domain.aliases import AliasEntityType, EntityAlias

    values: dict[str, object] = {
        "id": ALIAS_ID,
        "entity_type": AliasEntityType.SUPPLIER,
        "entity_id": SUPPLIER_ID,
        "alias": "Wärtsilä",
        "source_system": None,
    }
    values.update(overrides)
    with pytest.raises(DomainValidationError):
        EntityAlias(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "entity_type",
    [AliasEntityType.SUPPLIER, AliasEntityType.MATERIAL],
)
def test_global_master_alias_resolves_for_authenticated_user(
    entity_type: AliasEntityType,
) -> None:
    from packages.contracts.auth import UserContext
    from services.entity_resolution import EntityResolutionService

    alias = EntityAlias(
        id=ALIAS_ID,
        entity_type=entity_type,
        entity_id=SUPPLIER_ID,
        alias="explicit alias",
    )
    reader = _FakeAliasReader([alias])
    service = EntityResolutionService(reader, lambda _: None)

    assert service.resolve(
        entity_type=entity_type,
        raw_alias="EXPLICIT ALIAS",
        user_context=UserContext(user_id="authenticated-user"),
    ) == alias


def test_resolution_does_not_create_or_suggest_fuzzy_aliases() -> None:
    from packages.contracts.auth import UserContext
    from services.entity_resolution import EntityResolutionService

    explicit = EntityAlias(
        id=ALIAS_ID,
        entity_type=AliasEntityType.SUPPLIER,
        entity_id=SUPPLIER_ID,
        alias="Wartsila",
    )
    reader = _FakeAliasReader([explicit])
    service = EntityResolutionService(reader, lambda _: None)

    assert service.resolve(
        entity_type=AliasEntityType.SUPPLIER,
        raw_alias="Wartsilla",
        user_context=UserContext(user_id="authenticated-user"),
    ) is None
    assert reader.aliases == [explicit]
    assert reader.calls == [(AliasEntityType.SUPPLIER, "Wartsilla", None)]
