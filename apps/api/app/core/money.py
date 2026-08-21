from __future__ import annotations

from decimal import Decimal


def minor_to_decimal(amount_minor: int) -> Decimal:
    return (Decimal(amount_minor) / Decimal("100")).quantize(Decimal("0.01"))
