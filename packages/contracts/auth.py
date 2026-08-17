"""Transport-independent authentication and authorization contracts."""

from collections.abc import Set as AbstractSet
from enum import IntEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

type Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SecurityLevel(IntEnum):
    """Ordered information-security levels from least to most privileged."""

    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class UserContext(_FrozenContract):
    """Identity claims already authenticated by a trusted host adapter."""

    user_id: Identifier
    roles: AbstractSet[Identifier] = Field(default_factory=frozenset)
    departments: AbstractSet[Identifier] = Field(default_factory=frozenset)
    allowed_ship_ids: AbstractSet[Identifier] = Field(default_factory=frozenset)
    allowed_project_ids: AbstractSet[Identifier] = Field(default_factory=frozenset)
    security_clearance: SecurityLevel = SecurityLevel.PUBLIC


class AuthorizationScope(_FrozenContract):
    """Server-derived permissions; the default contains no scoped access."""

    roles: AbstractSet[Identifier] = Field(default_factory=frozenset)
    departments: AbstractSet[Identifier] = Field(default_factory=frozenset)
    allowed_ship_ids: AbstractSet[Identifier] = Field(default_factory=frozenset)
    allowed_project_ids: AbstractSet[Identifier] = Field(default_factory=frozenset)
    security_level: SecurityLevel = SecurityLevel.PUBLIC

    def intersection(self, other: Self) -> Self:
        """Return a scope no broader than either input scope."""
        return type(self)(
            roles=self.roles & other.roles,
            departments=self.departments & other.departments,
            allowed_ship_ids=self.allowed_ship_ids & other.allowed_ship_ids,
            allowed_project_ids=(
                self.allowed_project_ids & other.allowed_project_ids
            ),
            security_level=min(self.security_level, other.security_level),
        )
