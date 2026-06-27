from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


ZERO = Decimal("0")
MONEY_QUANT = Decimal("0.01")
WEIGHT_QUANT = Decimal("0.001")
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def to_decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    """Parse UI/OCR values such as '50.54 吨' or '2.17 %' into Decimal."""
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    text = str(value).strip().replace(",", "")
    if not text:
        return default

    match = NUMBER_RE.search(text)
    if not match:
        return default

    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return default


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def quantize_weight(value: Decimal) -> Decimal:
    return value.quantize(WEIGHT_QUANT, rounding=ROUND_HALF_UP)


def decimal_to_str(value: Decimal, *, places: int | None = None) -> str:
    if places == 2:
        return f"{quantize_money(value):.2f}"
    if places == 3:
        value = quantize_weight(value)

    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")
