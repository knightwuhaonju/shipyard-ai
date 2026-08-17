from dataclasses import FrozenInstanceError
from decimal import Decimal
from typing import Any, cast

import pytest


def test_positive_quantity_accepts_only_finite_positive_decimal() -> None:
    from packages.domain.value_objects import PositiveQuantity

    quantity = PositiveQuantity(Decimal("12.50"))

    assert quantity.value == Decimal("12.50")


@pytest.mark.parametrize(
    "value",
    [Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity")],
)
def test_positive_quantity_rejects_non_positive_or_non_finite_values(
    value: Decimal,
) -> None:
    from packages.domain.value_objects import (
        DomainValidationError,
        PositiveQuantity,
    )

    with pytest.raises(
        DomainValidationError,
        match="^quantity must be finite and greater than zero$",
    ):
        PositiveQuantity(value)


def test_positive_quantity_rejects_non_decimal_without_echoing_value() -> None:
    from packages.domain.value_objects import (
        DomainValidationError,
        PositiveQuantity,
    )

    secret_value = "customer-sensitive-quantity"
    with pytest.raises(DomainValidationError) as captured:
        PositiveQuantity(cast(Any, secret_value))

    assert str(captured.value) == "quantity must be a Decimal"
    assert secret_value not in str(captured.value)


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("0.5"), Decimal("1")])
def test_progress_accepts_inclusive_canonical_range(value: Decimal) -> None:
    from packages.domain.value_objects import Progress

    assert Progress(value).value == value


def test_progress_rejects_non_decimal_without_echoing_value() -> None:
    from packages.domain.value_objects import DomainValidationError, Progress

    secret_value = "customer-sensitive-progress"
    with pytest.raises(DomainValidationError) as captured:
        Progress(cast(Any, secret_value))

    assert str(captured.value) == "progress must be a Decimal"
    assert secret_value not in str(captured.value)


@pytest.mark.parametrize(
    "value",
    [Decimal("-0.01"), Decimal("1.01"), Decimal("NaN"), Decimal("Infinity")],
)
def test_progress_rejects_out_of_range_or_non_finite_values(value: Decimal) -> None:
    from packages.domain.value_objects import DomainValidationError, Progress

    with pytest.raises(
        DomainValidationError,
        match="^progress must be finite and between zero and one$",
    ):
        Progress(value)


def test_numeric_value_objects_are_immutable() -> None:
    from packages.domain.value_objects import PositiveQuantity, Progress

    quantity = PositiveQuantity(Decimal("1"))
    progress = Progress(Decimal("0.5"))

    with pytest.raises(FrozenInstanceError):
        cast(Any, quantity).value = Decimal("2")
    with pytest.raises(FrozenInstanceError):
        cast(Any, progress).value = Decimal("0.7")
