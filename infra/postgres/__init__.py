"""PostgreSQL persistence infrastructure."""

from infra.postgres.models import Base
from infra.postgres.repositories import (
    DomainRepository,
    UnsupportedDomainEntityError,
)

__all__ = [
    "Base",
    "DomainRepository",
    "UnsupportedDomainEntityError",
]
