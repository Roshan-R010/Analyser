"""Money in and out by payment mode, as percentages that always add up to exactly 100."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from analyser.model import ZERO, Transaction


@dataclass
class ModeShare:
    mode: str
    amount: Decimal
    entries: int
    percent: Decimal  # one decimal place; the list adds up to exactly 100.0


def shares_to_100(amounts: dict[str, Decimal]) -> dict[str, Decimal]:
    """Largest-remainder rounding to one decimal, so the shown percentages sum to 100.0."""
    total = sum(amounts.values(), ZERO)
    if not total:
        return {k: Decimal("0.0") for k in amounts}
    exact = {k: v * 1000 / total for k, v in amounts.items()}  # in tenths of a percent
    floors = {k: v.to_integral_value(rounding=ROUND_FLOOR) for k, v in exact.items()}
    left = int(1000 - sum(floors.values()))
    for k in sorted(exact, key=lambda k: exact[k] - floors[k], reverse=True)[:left]:
        floors[k] += 1
    return {k: v / 10 for k, v in floors.items()}


def build_mode_split(transactions: list[Transaction], credit: bool) -> list[ModeShare]:
    amounts: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    for t in transactions:
        amt = t.credit if credit else t.debit
        if amt:
            amounts[t.mode] = amounts.get(t.mode, ZERO) + amt
            counts[t.mode] = counts.get(t.mode, 0) + 1
    pct = shares_to_100(amounts)
    rows = [ModeShare(m, amounts[m], counts[m], pct[m]) for m in amounts]
    rows.sort(key=lambda r: (-r.amount, r.mode))
    return rows
