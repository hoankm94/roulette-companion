"""Dollar ↔ integer-cent conversion at the API boundary only."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


class MoneyError(ValueError):
    """Invalid monetary input."""


def dollars_to_cents(value: float | int | str | Decimal) -> int:
    """Convert a dollar amount to integer cents. Example: 13.68 -> 1368."""
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MoneyError(f"Invalid dollar amount: {value!r}") from exc
    if not dec.is_finite():
        raise MoneyError(f"Invalid dollar amount: {value!r}")
    cents = (dec * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def cents_to_dollars(cents: int | None) -> float | None:
    """Convert integer cents to dollars for API responses."""
    if cents is None:
        return None
    return float(Decimal(cents) / Decimal(100))
