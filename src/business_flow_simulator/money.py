"""Integer-cent money helpers. All amounts in this package are integer cents of a
fictional USD scenario. Floats are never used for money."""
from __future__ import annotations

BPS_DENOMINATOR = 10_000


class MoneyError(ValueError):
    """Raised when a value is not a valid integer amount in cents."""


def cents(value: object) -> int:
    """Validate that ``value`` is an int (not bool, not float) and return it."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise MoneyError(f"money must be an integer number of cents, got {value!r}")
    return value


def line_total(qty: int, unit_price_cents: int) -> int:
    if qty < 0:
        raise MoneyError(f"quantity must be non-negative, got {qty}")
    return cents(qty) * cents(unit_price_cents)


def apply_bps(amount_cents: int, bps: int) -> int:
    """Return ``amount`` adjusted by ``bps`` basis points using integer floor division."""
    amount = cents(amount_cents)
    return amount + (amount * cents(bps)) // BPS_DENOMINATOR


def format_usd(amount_cents: int) -> str:
    amount = cents(amount_cents)
    sign = "-" if amount < 0 else ""
    dollars, rem = divmod(abs(amount), 100)
    return f"{sign}USD {dollars}.{rem:02d}"
