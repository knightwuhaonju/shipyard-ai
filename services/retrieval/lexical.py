"""Validated service boundary for lexical knowledge retrieval."""

from __future__ import annotations

from typing import Protocol

from packages.contracts import AuthorizationScope, KnowledgeEvidence, KnowledgeFilters

MAX_QUERY_CHARS = 1000
MAX_RETRIEVAL_RESULTS = 20
_INVALID_REQUEST = "invalid lexical retrieval request"


class RetrievalValidationError(ValueError):
    """Raised when a lexical request violates the public service contract."""


class LexicalRetrievalError(RuntimeError):
    """Raised when an otherwise valid lexical search cannot be completed."""


class LexicalSearchPort(Protocol):
    """Port implemented by approved lexical search infrastructure."""

    def search(
        self,
        query: str,
        user_scope: AuthorizationScope,
        filters: KnowledgeFilters,
        limit: int,
    ) -> list[KnowledgeEvidence]: ...


class LexicalRetriever:
    """Validate trusted retrieval inputs before delegating to the search port."""

    def __init__(self, port: LexicalSearchPort) -> None:
        self._port = port

    def retrieve(
        self,
        query: str,
        user_scope: AuthorizationScope,
        filters: KnowledgeFilters,
        limit: int = 10,
    ) -> list[KnowledgeEvidence]:
        normalized_query = self._validated_query(query)
        if type(user_scope) is not AuthorizationScope:
            raise RetrievalValidationError(_INVALID_REQUEST)
        if type(filters) is not KnowledgeFilters:
            raise RetrievalValidationError(_INVALID_REQUEST)
        if type(limit) is not int or not 1 <= limit <= MAX_RETRIEVAL_RESULTS:
            raise RetrievalValidationError(_INVALID_REQUEST)
        return self._port.search(normalized_query, user_scope, filters, limit)

    @staticmethod
    def _validated_query(query: str) -> str:
        if type(query) is not str:
            raise RetrievalValidationError(_INVALID_REQUEST)
        normalized_query = query.strip()
        if (
            not normalized_query
            or "\x00" in normalized_query
            or len(normalized_query) > MAX_QUERY_CHARS
        ):
            raise RetrievalValidationError(_INVALID_REQUEST)
        return normalized_query
