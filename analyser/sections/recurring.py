"""Recurring debits: the same party paid again and again.

One row per party (not per exact amount). Counted as recurring only with at least
3 payments spread over at least 2 months. Cash, own-account transfers, charges and
unknown entries are not "recurring payments".
"""
from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from analyser.model import ZERO, Transaction

EXCLUDE = {"_CASH", "_SELF", "_CHARGES", "_INTEREST", "_RETURNS", "_UNKNOWN"}
MIN_PAYMENTS = 3
MIN_MONTHS = 2
MIN_TOTAL = Decimal("10000")  # smaller repeat spends (fuel, food) only lengthen the report


@dataclass
class RecurringRow:
    party: str
    key: str
    description: str  # a typical description
    total: Decimal
    entries: int
    amounts: list[tuple[Decimal, int]]  # (amount, times), most common first
    interval: str
    dates: list[date]
    lender: str


def interval_label(dates: list[date]) -> str:
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    if not gaps:
        return "-"
    months = len({d.replace(day=1) for d in dates})
    per_month = len(dates) / months
    if per_month >= 4:
        return f"Frequent (~{per_month:.0f}/month)"
    g = statistics.median(gaps)
    spread = statistics.pstdev(gaps) if len(gaps) > 1 else 0
    if g <= 2:
        label = "Daily"
    elif 5 <= g <= 9:
        label = "Weekly"
    elif 12 <= g <= 18:
        label = "Fortnightly"
    elif 25 <= g <= 35:
        label = "Monthly"
    elif 80 <= g <= 100:
        label = "Quarterly"
    else:
        return "Irregular"
    # Mostly irregular gaps around that median: say so
    return label if spread <= max(4, g * 0.5) else "Irregular"


def build_recurring(transactions: list[Transaction]) -> list[RecurringRow]:
    by: dict[str, list[Transaction]] = {}
    for t in transactions:
        if t.debit and t.party_key not in EXCLUDE:
            by.setdefault(t.party_key, []).append(t)
    rows = []
    for key, tx in by.items():
        tx.sort(key=lambda t: t.date)
        months = {t.date.replace(day=1) for t in tx}
        total = sum((t.debit for t in tx), ZERO)
        is_lender = any(t.lender for t in tx)
        if len(tx) < MIN_PAYMENTS or len(months) < MIN_MONTHS or (total < MIN_TOTAL and not is_lender):
            continue
        amounts = Counter(t.debit for t in tx).most_common()
        rows.append(RecurringRow(
            party=tx[0].party_clean, key=key,
            description=Counter(t.description for t in tx).most_common(1)[0][0],
            total=sum((t.debit for t in tx), ZERO), entries=len(tx), amounts=amounts,
            interval=interval_label([t.date for t in tx]), dates=[t.date for t in tx],
            lender=next((t.lender for t in tx if t.lender), ""),
        ))
    rows.sort(key=lambda r: (-r.total, r.party))
    return rows
