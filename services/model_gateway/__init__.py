"""Vendor-neutral model gateway contracts."""

from services.model_gateway.embedding import (
    EmbeddingAdapterError,
    EmbeddingGateway,
    EmbeddingPort,
    EmbeddingProfile,
    EmbeddingUnavailableError,
    EmbeddingValidationError,
)

__all__ = [
    "EmbeddingAdapterError",
    "EmbeddingGateway",
    "EmbeddingPort",
    "EmbeddingProfile",
    "EmbeddingUnavailableError",
    "EmbeddingValidationError",
]
