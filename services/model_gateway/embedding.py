"""Strict vendor-neutral boundary for text embedding adapters."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Protocol

MAX_EMBEDDING_MODEL_ID_CHARS = 128
MAX_EMBEDDING_DIMENSION = 2000
MAX_EMBEDDING_BATCH_SIZE = 128
MAX_EMBEDDING_TEXT_CHARS = 2000
_INVALID_PROFILE = "invalid embedding profile"
_INVALID_REQUEST = "invalid embedding request"
_UNAVAILABLE = "embedding unavailable"


class EmbeddingAdapterError(RuntimeError):
    """Raised by an adapter after it translates a provider failure."""


class EmbeddingValidationError(ValueError):
    """Raised when embedding configuration or requests violate this contract."""


class EmbeddingUnavailableError(RuntimeError):
    """Raised when an adapter cannot provide a valid embedding result."""


@dataclass(frozen=True, slots=True, kw_only=True)
class EmbeddingProfile:
    """Explicit, validated configuration for one embedding space."""

    model_id: str
    dimension: int

    def __post_init__(self) -> None:
        if (
            type(self.model_id) is not str
            or not self.model_id.strip()
            or "\x00" in self.model_id
            or len(self.model_id) > MAX_EMBEDDING_MODEL_ID_CHARS
            or type(self.dimension) is not int
            or not 1 <= self.dimension <= MAX_EMBEDDING_DIMENSION
        ):
            raise EmbeddingValidationError(_INVALID_PROFILE)


class EmbeddingPort(Protocol):
    """Port implemented by a provider-specific embedding adapter."""

    @property
    def profile(self) -> EmbeddingProfile: ...

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]: ...


class EmbeddingGateway:
    """Validate requests and adapter output without changing vector semantics."""

    def __init__(self, adapter: EmbeddingPort) -> None:
        self._adapter = adapter
        self._profile = adapter.profile

    @property
    def profile(self) -> EmbeddingProfile:
        """Return the adapter's explicit embedding-space profile unchanged."""
        return self._profile

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        self._validate_texts(texts)
        try:
            vectors = self._adapter.embed(texts)
        except EmbeddingAdapterError:
            raise EmbeddingUnavailableError(_UNAVAILABLE) from None
        if not self._valid_vectors(vectors, text_count=len(texts)):
            raise EmbeddingUnavailableError(_UNAVAILABLE) from None
        return vectors

    @staticmethod
    def _validate_texts(texts: tuple[str, ...]) -> None:
        if (
            type(texts) is not tuple
            or not texts
            or len(texts) > MAX_EMBEDDING_BATCH_SIZE
        ):
            raise EmbeddingValidationError(_INVALID_REQUEST)
        if any(
            type(text) is not str
            or not text.strip()
            or "\x00" in text
            or len(text) > MAX_EMBEDDING_TEXT_CHARS
            for text in texts
        ):
            raise EmbeddingValidationError(_INVALID_REQUEST)

    def _valid_vectors(self, vectors: object, *, text_count: int) -> bool:
        if type(vectors) is not tuple or len(vectors) != text_count:
            return False
        return all(self._valid_vector(vector) for vector in vectors)

    def _valid_vector(self, vector: object) -> bool:
        if type(vector) is not tuple or len(vector) != self._profile.dimension:
            return False
        norm_squared = 0.0
        for component in vector:
            if type(component) is not float or not isfinite(component):
                return False
            norm_squared += component * component
        return norm_squared != 0.0
