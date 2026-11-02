"""Exact commercial values and refusal helpers shared by LBX offer normalizers."""

from __future__ import annotations

from decimal import Decimal
from typing import NoReturn, TypeVar

from app.domains.catalog.commercial_offer import OfferRefusalKind, SelectedOfferRefused
from app.integrations.lbx.dto import LbxTariffService


# Finite representation limits, not provider monetary precision or SLAs.
MAX_EXACT_DIGITS = 256
MAX_MONEY_SCALE = 36
T = TypeVar("T")


def _incomplete(reason: str) -> NoReturn:
    raise SelectedOfferRefused(OfferRefusalKind.INCOMPLETE, reason)


def _required(value: T | None, reason: str) -> T:
    if value is None:
        _incomplete(reason)
    assert value is not None
    return value


def _exact(value: Decimal | None, reason: str) -> Decimal:
    result = _required(value, reason)
    if not isinstance(result, Decimal) or not result.is_finite():
        _incomplete(reason)
    parts = result.as_tuple()
    if len(parts.digits) > MAX_EXACT_DIGITS or abs(int(parts.exponent)) > MAX_EXACT_DIGITS:
        _incomplete("numeric_representation_unsupported")
    return result


def _minor_units(value: Decimal, scale: int) -> int:
    """Check exact divisibility without quantize(), float or Decimal context."""
    value = _exact(value, "money_invalid")
    parts = value.as_tuple()
    coefficient = int("".join(str(digit) for digit in parts.digits))
    exponent = int(parts.exponent) + scale
    if exponent >= 0:
        units = coefficient * 10**exponent
    else:
        units, remainder = divmod(coefficient, 10**-exponent)
        if remainder:
            _incomplete("money_scale_mismatch")
    return -units if parts.sign else units


def _multiply(left: Decimal, right: Decimal) -> Decimal:
    """Exact product even when source digits exceed the default context's 28."""
    a, b = left.as_tuple(), right.as_tuple()
    coefficient = int("".join(map(str, a.digits))) * int("".join(map(str, b.digits)))
    result = Decimal((a.sign ^ b.sign, tuple(map(int, str(coefficient))), int(a.exponent) + int(b.exponent)))
    return _exact(result, "money_invalid")


def _quantity_bounds(service: LbxTariffService) -> tuple[int, int]:
    minimum = _exact(service.min_multiplicator, "commercial_minimum_unknown")
    maximum = _exact(service.max_multiplicator, "commercial_maximum_unknown")
    if minimum < 0 or minimum > maximum:
        _incomplete("commercial_bounds_invalid")
    if any(value != value.to_integral_value() for value in (minimum, maximum)):
        raise SelectedOfferRefused(OfferRefusalKind.NOT_SELLABLE, "commercial_quantity_not_integer")
    # Conversion follows the exact integral check; no rounding/truncation.
    return int(minimum), int(maximum)
