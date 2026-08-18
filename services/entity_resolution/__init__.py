"""Authorization-aware canonical entity resolution."""

from services.entity_resolution.service import (
    AliasReader,
    EntityResolutionService,
)

__all__ = ["AliasReader", "EntityResolutionService"]
