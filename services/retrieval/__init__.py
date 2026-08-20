"""Transport-independent retrieval service interfaces."""

from services.retrieval.lexical import (
    LexicalRetrievalError,
    LexicalRetriever,
    LexicalSearchPort,
    RetrievalValidationError,
)
from services.retrieval.vector import (
    VectorRetrievalError,
    VectorRetrievalValidationError,
    VectorRetriever,
    VectorSearchPort,
)

__all__ = [
    "LexicalRetrievalError",
    "LexicalRetriever",
    "LexicalSearchPort",
    "RetrievalValidationError",
    "VectorRetrievalError",
    "VectorRetrievalValidationError",
    "VectorRetriever",
    "VectorSearchPort",
]
