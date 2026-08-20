"""Transport-independent retrieval service interfaces."""

from services.retrieval.lexical import (
    LexicalRetrievalError,
    LexicalRetriever,
    LexicalSearchPort,
    RetrievalValidationError,
)

__all__ = [
    "LexicalRetrievalError",
    "LexicalRetriever",
    "LexicalSearchPort",
    "RetrievalValidationError",
]
