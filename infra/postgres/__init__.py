"""PostgreSQL persistence infrastructure."""

from infra.postgres.models import Base
from infra.postgres.repositories import (
    DomainPersistenceError,
    DomainRepository,
    UnsupportedDomainEntityError,
)

__all__ = [
    "Base",
    "DomainPersistenceError",
    "DomainRepository",
    "UnsupportedDomainEntityError",
]
