"""Insert-only PostgreSQL persistence for deterministic chunk embeddings."""

from array import array
from math import isfinite
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from infra.postgres.document_models import (
    DATABASE_EMBEDDING_DIMENSION,
    DATABASE_EMBEDDING_MODEL_ID,
    DocumentChunkEmbeddingModel,
)
from services.model_gateway import EmbeddingProfile

_PERSISTENCE_ERROR = "embedding record violates persistence constraints"


class EmbeddingPersistenceError(RuntimeError):
    """Raised when a chunk embedding violates persistence constraints."""


def _validated_embedding(embedding: object) -> list[float]:
    if (
        type(embedding) is not tuple
        or len(embedding) != DATABASE_EMBEDDING_DIMENSION
        or any(type(component) is not float for component in embedding)
        or any(not isfinite(component) for component in embedding)
    ):
        raise EmbeddingPersistenceError(_PERSISTENCE_ERROR)
    try:
        stored_embedding = array("f", embedding)
    except (OverflowError, TypeError, ValueError):
        raise EmbeddingPersistenceError(_PERSISTENCE_ERROR) from None
    if not any(component != 0.0 for component in stored_embedding):
        raise EmbeddingPersistenceError(_PERSISTENCE_ERROR)
    return stored_embedding.tolist()


class PostgresEmbeddingRepository:
    """Insert chunk embeddings in a caller-owned SQLAlchemy session."""

    def __init__(self, session: Session, profile: EmbeddingProfile) -> None:
        if (
            type(profile) is not EmbeddingProfile
            or profile.model_id != DATABASE_EMBEDDING_MODEL_ID
            or profile.dimension != DATABASE_EMBEDDING_DIMENSION
        ):
            raise EmbeddingPersistenceError(_PERSISTENCE_ERROR)
        self._session = session
        self._profile = profile

    def insert(self, chunk_id: UUID, embedding: tuple[float, ...]) -> None:
        if type(chunk_id) is not UUID:
            raise EmbeddingPersistenceError(_PERSISTENCE_ERROR)
        stored_embedding = _validated_embedding(embedding)
        try:
            with self._session.begin_nested():
                self._session.add(
                    DocumentChunkEmbeddingModel(
                        chunk_id=chunk_id,
                        embedding_model=self._profile.model_id,
                        embedding=stored_embedding,
                    )
                )
                self._session.flush()
        except IntegrityError:
            raise EmbeddingPersistenceError(_PERSISTENCE_ERROR) from None
