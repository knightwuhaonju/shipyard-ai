"""Validated service orchestration for vector knowledge retrieval."""

from __future__ import annotations

from typing import Protocol

from packages.contracts import AuthorizationScope, KnowledgeEvidence, KnowledgeFilters
from services.model_gateway import (
    EmbeddingGateway,
    EmbeddingProfile,
    EmbeddingUnavailableError,
)

MAX_QUERY_CHARS = 1000
MAX_RETRIEVAL_RESULTS = 20
_INVALID_REQUEST = "invalid vector retrieval request"
_UNAVAILABLE = "vector retrieval unavailable"


class VectorRetrievalValidationError(ValueError):
    """Raised when a vector request violates the public service contract."""


class VectorRetrievalError(RuntimeError):
    """Raised when an otherwise valid vector search cannot be completed."""


class VectorSearchPort(Protocol):
    """Port implemented by approved vector search infrastructure."""

    def search(
        self,
        query: str,
        query_embedding: tuple[float, ...],
        profile: EmbeddingProfile,
        user_scope: AuthorizationScope,
        filters: KnowledgeFilters,
        limit: int,
    ) -> list[KnowledgeEvidence]: ...


class VectorRetriever:
    """Validate trusted inputs, embed once, and delegate one vector search."""

    def __init__(
        self, gateway: EmbeddingGateway, search_port: VectorSearchPort
    ) -> None:
        self._gateway = gateway
        self._search_port = search_port

    def retrieve(
        self,
        query: str,
        user_scope: AuthorizationScope,
        filters: KnowledgeFilters,
        limit: int = 10,
    ) -> list[KnowledgeEvidence]:
        normalized_query = self._validated_query(query)
        if type(user_scope) is not AuthorizationScope:
            raise VectorRetrievalValidationError(_INVALID_REQUEST)
        if type(filters) is not KnowledgeFilters:
            raise VectorRetrievalValidationError(_INVALID_REQUEST)
        if type(limit) is not int or not 1 <= limit <= MAX_RETRIEVAL_RESULTS:
            raise VectorRetrievalValidationError(_INVALID_REQUEST)

        try:
            query_embedding = self._gateway.embed((normalized_query,))[0]
        except EmbeddingUnavailableError:
            raise VectorRetrievalError(_UNAVAILABLE) from None

        return self._search_port.search(
            normalized_query,
            query_embedding,
            self._gateway.profile,
            user_scope,
            filters,
            limit,
        )

    @staticmethod
    def _validated_query(query: str) -> str:
        if type(query) is not str:
            raise VectorRetrievalValidationError(_INVALID_REQUEST)
        normalized_query = query.strip()
        if (
            not normalized_query
            or "\x00" in normalized_query
            or len(normalized_query) > MAX_QUERY_CHARS
        ):
            raise VectorRetrievalValidationError(_INVALID_REQUEST)
        return normalized_query
