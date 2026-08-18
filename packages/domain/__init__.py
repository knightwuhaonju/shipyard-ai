"""Framework-independent Shipyard AI domain model."""

from packages.domain.aliases import AliasEntityType, EntityAlias, normalize_alias
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
    "Drawing",
    "Equipment",
    "EntityAlias",
    "Material",
    "normalize_alias",
    "PositiveQuantity",
    "Progress",
    "ProjectTask",
    "PurchaseOrder",
    "Ship",
    "ShipSystem",
    "Supplier",
]
