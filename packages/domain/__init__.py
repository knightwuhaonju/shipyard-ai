"""Framework-independent Shipyard AI domain model."""

from packages.domain.aliases import AliasEntityType, EntityAlias, normalize_alias
from packages.domain.documents import (
    Document,
    DocumentChunk,
    DocumentValidationError,
    DocumentVersion,
    document_chunk_id,
)
from packages.domain.entities import (
    BOMItem,
    Drawing,
    Equipment,
    Material,
    ProjectTask,
    PurchaseOrder,
    Ship,
    ShipSystem,
    Supplier,
)
from packages.domain.value_objects import (
    DomainValidationError,
    PositiveQuantity,
    Progress,
)

__all__ = [
    "AliasEntityType",
    "BOMItem",
    "DomainValidationError",
    "Document",
    "DocumentChunk",
    "DocumentValidationError",
    "DocumentVersion",
    "Drawing",
    "Equipment",
    "EntityAlias",
    "Material",
    "normalize_alias",
    "document_chunk_id",
    "PositiveQuantity",
    "Progress",
    "ProjectTask",
    "PurchaseOrder",
    "Ship",
    "ShipSystem",
    "Supplier",
]
