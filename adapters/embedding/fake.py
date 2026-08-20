"""Deterministic in-memory embedding adapter for tests and local checks."""

from __future__ import annotations

from collections.abc import Mapping

from services.model_gateway.embedding import EmbeddingAdapterError, EmbeddingProfile

_INVALID_CONFIGURATION = "invalid fake embedding configuration"


class FakeEmbeddingAdapter:
    """Return explicitly configured vectors in input order without side effects."""

    def __init__(
        self, profile: EmbeddingProfile, vectors: Mapping[str, tuple[float, ...]]
    ) -> None:
        if type(profile) is not EmbeddingProfile or not isinstance(vectors, Mapping):
            raise ValueError(_INVALID_CONFIGURATION)
        copied_vectors: dict[str, tuple[float, ...]] = {}
        for text, vector in vectors.items():
            if not self._valid_entry(profile, text, vector):
                raise ValueError(_INVALID_CONFIGURATION)
            copied_vectors[text] = vector
        self._profile = profile
        self._vectors = copied_vectors
        self._calls: list[tuple[str, ...]] = []

    @property
    def profile(self) -> EmbeddingProfile:
        """Return the explicit profile object supplied at construction."""
        return self._profile

    @property
    def calls(self) -> tuple[tuple[str, ...], ...]:
        """Return all embedding requests in their original order."""
        return tuple(self._calls)

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        self._calls.append(texts)
        try:
            return tuple(self._vectors[text] for text in texts)
        except KeyError:
            raise EmbeddingAdapterError("embedding adapter failed") from None

    @staticmethod
    def _valid_entry(
        profile: EmbeddingProfile, text: object, vector: object
    ) -> bool:
        if (
            type(text) is not str
            or not text.strip()
            or "\x00" in text
            or len(text) > 2000
        ):
            return False
        if type(vector) is not tuple or len(vector) != profile.dimension:
            return False
        norm_squared = 0.0
        for component in vector:
            if (
                type(component) is not float
                or not -float("inf") < component < float("inf")
            ):
                return False
            norm_squared += component * component
        return norm_squared != 0.0
