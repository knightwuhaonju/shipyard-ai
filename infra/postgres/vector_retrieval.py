"""ACL-filtered PostgreSQL cosine retrieval over stored chunk embeddings."""

from __future__ import annotations

from math import isfinite

from sqlalchemy import bindparam, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from infra.postgres.document_models import (
    DATABASE_EMBEDDING_DIMENSION,
    DATABASE_EMBEDDING_MODEL_ID,
    DocumentChunkEmbeddingModel,
    DocumentChunkModel,
    DocumentModel,
    DocumentVersionModel,
)
from infra.postgres.retrieval_support import (
    authorized_document_constraints,
    evidence_excerpt,
)
from packages.contracts import AuthorizationScope, KnowledgeEvidence, KnowledgeFilters
from services.model_gateway import EmbeddingProfile
from services.retrieval.vector import VectorRetrievalError, VectorSearchPort

_UNAVAILABLE = "vector retrieval unavailable"


class PostgresVectorSearchAdapter(VectorSearchPort):
    """Execute one bounded ACL-aware cosine query in a private session."""

    def __init__(self, engine: Engine, profile: EmbeddingProfile) -> None:
        if (
            type(profile) is not EmbeddingProfile
            or profile.model_id != DATABASE_EMBEDDING_MODEL_ID
            or profile.dimension != DATABASE_EMBEDDING_DIMENSION
        ):
            raise VectorRetrievalError(_UNAVAILABLE) from None
        self._engine = engine
        self._profile = profile

    def search(
        self,
        query: str,
        query_embedding: tuple[float, ...],
        profile: EmbeddingProfile,
        user_scope: AuthorizationScope,
        filters: KnowledgeFilters,
        limit: int,
    ) -> list[KnowledgeEvidence]:
        if (
            type(profile) is not EmbeddingProfile
            or profile != self._profile
            or type(query_embedding) is not tuple
            or len(query_embedding) != DATABASE_EMBEDDING_DIMENSION
        ):
            raise VectorRetrievalError(_UNAVAILABLE) from None

        distance = DocumentChunkEmbeddingModel.embedding.cosine_distance(
            bindparam("query_embedding")
        ).label("distance")
        authorization_predicates, authorization_parameters = (
            authorized_document_constraints(user_scope, filters)
        )
        parameters: dict[str, object] = {
            **authorization_parameters,
            "embedding_model": profile.model_id,
            "query_embedding": list(query_embedding),
            "limit": limit,
        }
        statement = (
            select(
                DocumentModel.document_id.label("document_id"),
                DocumentVersionModel.version_id.label("version_id"),
                DocumentChunkModel.chunk_id.label("chunk_id"),
                DocumentModel.title.label("title"),
                DocumentChunkModel.section.label("section"),
                DocumentChunkModel.page.label("page"),
                DocumentVersionModel.source_uri.label("source_uri"),
                DocumentChunkModel.normalized_text.label("normalized_text"),
                distance,
            )
            .select_from(DocumentChunkEmbeddingModel)
            .join(
                DocumentChunkModel,
                DocumentChunkModel.chunk_id
                == DocumentChunkEmbeddingModel.chunk_id,
            )
            .join(
                DocumentVersionModel,
                DocumentVersionModel.version_id == DocumentChunkModel.version_id,
            )
            .join(
                DocumentModel,
                DocumentModel.document_id == DocumentVersionModel.document_id,
            )
            .where(
                DocumentChunkEmbeddingModel.embedding_model
                == bindparam("embedding_model"),
                *authorization_predicates,
            )
            .order_by(
                distance.asc(),
                DocumentVersionModel.source_updated_at.desc(),
                DocumentChunkModel.chunk_id.asc(),
            )
            .limit(bindparam("limit"))
        )

        try:
            with Session(self._engine) as session, session.begin():
                session.execute(text("SET TRANSACTION READ ONLY"))
                session.execute(text("SET LOCAL statement_timeout = 2000"))
                rows = session.execute(statement, parameters).all()
        except SQLAlchemyError:
            raise VectorRetrievalError(_UNAVAILABLE) from None

        evidence: list[KnowledgeEvidence] = []
        for row in rows:
            distance_value = float(row.distance)
            if not isfinite(distance_value):
                raise VectorRetrievalError(_UNAVAILABLE) from None
            score = max(0.0, 1.0 - distance_value)
            evidence.append(
                KnowledgeEvidence(
                    document_id=row.document_id,
                    version_id=row.version_id,
                    chunk_id=row.chunk_id,
                    title=row.title,
                    section=row.section,
                    page=row.page,
                    source_uri=row.source_uri,
                    excerpt=evidence_excerpt(row.normalized_text, query),
                    retrieval_score=score,
                    vector_score=score,
                )
            )
        return evidence
