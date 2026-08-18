"""PostgreSQL persistence infrastructure."""

from infra.postgres.alias_repository import AliasPersistenceError, AliasRepository
from infra.postgres.models import Base
from infra.postgres.repositories import (
    DomainPersistenceError,
    DomainRepository,
    UnsupportedDomainEntityError,
)

__all__ = [
    "AliasPersistenceError",
    "AliasRepository",
    "Base",
    "DomainPersistenceError",
    "DomainRepository",
    "UnsupportedDomainEntityError",
]
