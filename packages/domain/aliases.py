"""Immutable explicit aliases for canonical shipyard entities."""

from dataclasses import dataclass, field
from enum import StrEnum
from unicodedata import normalize
from uuid import UUID

from packages.domain.value_objects import DomainValidationError


class AliasEntityType(StrEnum):
    """Canonical entity types supported by explicit alias resolution."""

    SUPPLIER = "supplier"
    EQUIPMENT = "equipment"
    MATERIAL = "material"


def normalize_alias(value: str) -> str:
    """Return the deterministic exact-lookup key for an explicit alias."""
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError("alias must be non-blank text")
    return " ".join(normalize("NFKC", value).casefold().split())


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityAlias:
    """An explicit textual link to one canonical entity UUID."""

    id: UUID
    entity_type: AliasEntityType
    entity_id: UUID
    alias: str
    source_system: str | None = None
    normalized_alias: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise DomainValidationError("id must be a UUID")
        if not isinstance(self.entity_type, AliasEntityType):
            raise DomainValidationError("entity_type is unsupported")
        if not isinstance(self.entity_id, UUID):
            raise DomainValidationError("entity_id must be a UUID")
        if self.source_system is not None and (
            not isinstance(self.source_system, str) or not self.source_system.strip()
        ):
            raise DomainValidationError(
                "source_system must be non-blank when provided"
            )
        object.__setattr__(self, "normalized_alias", normalize_alias(self.alias))
