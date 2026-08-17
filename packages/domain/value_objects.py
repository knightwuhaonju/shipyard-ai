"""Framework-independent constrained domain values."""

from dataclasses import dataclass
from decimal import Decimal


class DomainValidationError(ValueError):
    """Raised when normalized data violates a domain invariant."""


@dataclass(frozen=True, slots=True)
class PositiveQuantity:
    """A finite quantity strictly greater than zero."""

    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise DomainValidationError("quantity must be a Decimal")
        if not self.value.is_finite() or self.value <= 0:
            raise DomainValidationError("quantity must be finite and greater than zero")


@dataclass(frozen=True, slots=True)
class Progress:
    """Canonical finite progress ratio in the inclusive zero-to-one range."""

    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise DomainValidationError("progress must be a Decimal")
        if (
            not self.value.is_finite()
            or not Decimal("0") <= self.value <= Decimal("1")
        ):
            raise DomainValidationError(
                "progress must be finite and between zero and one"
            )
