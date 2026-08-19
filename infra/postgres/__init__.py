"""PostgreSQL persistence infrastructure."""

from infra.postgres.alias_repository import AliasPersistenceError, AliasRepository
from infra.postgres.document_models import (
    DocumentChunkModel,
    DocumentModel,
    DocumentVersionModel,
)
from infra.postgres.document_repository import PostgresDocumentRepository
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
    "DocumentChunkModel",
    "DocumentModel",
    "DocumentVersionModel",
    "DomainPersistenceError",
    "DomainRepository",
    "PostgresDocumentRepository",
    "UnsupportedDomainEntityError",
]
