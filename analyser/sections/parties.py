"""Counterparty totals per month, and unknown transactions.

Every transaction lands in exactly one row of its month (a party, Cash, Self, Charges,
Interest, Returns, Unknown, or the "Txn total < 5K" row), so each side's rows always
add up to that month's credit or debit total. That is checked in checks.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from analyser.enrich.parties import UNKNOWN
from analyser.model import ZERO, Transaction

SMALL = Decimal("5000")  # parties below this per month are grouped into one row
SMALL_LABEL = "Txn total < 5K"
UNKNOWN_LIST_MIN = Decimal("10000")


@dataclass
class PartyRow:
    name: str
    key: str
    amount: Decimal
    entries: int


@dataclass
class MonthParties:
    month: date
    credit_total: Decimal
    credit_entries: int
    debit_total: Decimal
    debit_entries: int
    credits: list[PartyRow]
    debits: list[PartyRow]


@dataclass
class UnknownSection:
    listed: list[Transaction]  # unknown entries of UNKNOWN_LIST_MIN or more
    small_count: int
    small_total: Decimal


def _side(txns: list[Transaction], credit: bool) -> list[PartyRow]:
    by: dict[str, PartyRow] = {}
    for t in txns:
        amt = t.credit if credit else t.debit
        if not amt:
            continue
        row = by.setdefault(t.party_key, PartyRow(t.party_clean or UNKNOWN, t.party_key, ZERO, 0))
        row.amount += amt
        row.entries += 1
    big = [r for r in by.values() if r.amount >= SMALL]
    small = [r for r in by.values() if r.amount < SMALL]
    big.sort(key=lambda r: (-r.amount, r.name))
    if small:
        big.append(PartyRow(SMALL_LABEL, "_SMALL", sum((r.amount for r in small), ZERO),
                            sum(r.entries for r in small)))
    return big


def build_month_parties(transactions: list[Transaction]) -> list[MonthParties]:
    months: dict[date, list[Transaction]] = {}
    for t in transactions:
        months.setdefault(t.date.replace(day=1), []).append(t)
    out = []
    for m in sorted(months):
        tx = months[m]
        out.append(MonthParties(
            month=m,
            credit_total=sum((t.credit for t in tx), ZERO),
            credit_entries=sum(1 for t in tx if t.credit),
            debit_total=sum((t.debit for t in tx), ZERO),
            debit_entries=sum(1 for t in tx if t.debit),
            credits=_side(tx, credit=True),
            debits=_side(tx, credit=False),
        ))
    return out


def build_unknown(transactions: list[Transaction]) -> UnknownSection:
    unknown = [t for t in transactions if t.party_key == "_UNKNOWN"]
    listed = [t for t in unknown if (t.credit or t.debit) >= UNKNOWN_LIST_MIN]
    small = [t for t in unknown if (t.credit or t.debit) < UNKNOWN_LIST_MIN]
    return UnknownSection(listed=listed, small_count=len(small),
                          small_total=sum((t.credit + t.debit for t in small), ZERO))
