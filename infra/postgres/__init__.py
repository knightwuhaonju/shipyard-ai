"""PostgreSQL persistence infrastructure."""

from infra.postgres.alias_repository import AliasPersistenceError, AliasRepository
from infra.postgres.document_models import (
    DATABASE_EMBEDDING_DIMENSION,
    DATABASE_EMBEDDING_MODEL_ID,
    DocumentChunkEmbeddingModel,
    DocumentChunkModel,
    DocumentModel,
    DocumentVersionModel,
)
from infra.postgres.document_repository import PostgresDocumentRepository
from infra.postgres.embedding_repository import (
    EmbeddingPersistenceError,
    PostgresEmbeddingRepository,
)
from infra.postgres.lexical_retrieval import PostgresLexicalSearchAdapter
from infra.postgres.models import Base
from infra.postgres.repositories import (
    DomainPersistenceError,
    DomainRepository,
    UnsupportedDomainEntityError,
)
from infra.postgres.vector_retrieval import PostgresVectorSearchAdapter

__all__ = [
    "AliasPersistenceError",
    "AliasRepository",
    "Base",
    "DATABASE_EMBEDDING_DIMENSION",
    "DATABASE_EMBEDDING_MODEL_ID",
    "DocumentChunkEmbeddingModel",
    "DocumentChunkModel",
    "DocumentModel",
    "DocumentVersionModel",
    "DomainPersistenceError",
    "DomainRepository",
    "EmbeddingPersistenceError",
    "PostgresDocumentRepository",
    "PostgresEmbeddingRepository",
    "PostgresLexicalSearchAdapter",
    "PostgresVectorSearchAdapter",
    "UnsupportedDomainEntityError",
]
