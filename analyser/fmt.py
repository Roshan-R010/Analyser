"""Rupee amounts as printed in the report: Indian digit grouping (12,34,567), halves rounded up.

One place for every screen, page and command-line line, so the same amount never reads two ways.
"""
from __future__ import annotations

from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

NONE = "–"  # shown where there is no amount


def _group(digits: str) -> str:
    """'1234567' -> '12,34,567'."""
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def _signed(negative: bool, text: str) -> str:
    return f"-{text}" if negative else text


def inr(x) -> str:
    """Whole rupees: 1234567.5 -> 12,34,568. None -> '–'."""
    if x is None:
        return NONE
    whole = Decimal(x).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return _signed(whole < 0, _group(str(abs(whole))))  # -0.4 rounds to 0, never "-0"


def inr2(x) -> str:
    """With paise only when there are paise: 30,851.88 / 42,432. None -> '–'."""
    if x is None:
        return NONE
    x = Decimal(x)
    if x == x.to_integral_value():
        return inr(x)
    paise = f"{abs(x):.2f}".split(".")[1]
    whole = abs(x).to_integral_value(rounding=ROUND_FLOOR)
    if paise == "00":  # 0.004 rounds to .00: show it as a whole amount
        return inr(x)
    return _signed(x < 0, f"{_group(str(whole))}.{paise}")


def inr_paise(x) -> str:
    """Always two decimals: 1234567.5 -> 12,34,567.50. None -> '-'."""
    if x is None:
        return "-"
    x = Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    whole, frac = f"{abs(x):.2f}".split(".")
    return _signed(x < 0, f"{_group(whole)}.{frac}")
