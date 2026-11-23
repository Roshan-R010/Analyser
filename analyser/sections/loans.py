"""Loans: every entry with a lender, grouped by lender, with one summary line each.

Summary per lender: type, usual EMI, months paid, months missed between the first and
last payment, months paid in pieces, bounced payments, and money received (disbursements).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from analyser.model import ZERO, Transaction
from analyser.sections.returns import ReturnsSection


@dataclass
class LenderLoan:
    lender: str
    type: str
    entries: list[Transaction]
    emi: Decimal | None  # most common payment amount (None if fewer than 2 payments)
    paid_total: Decimal
    received_total: Decimal
    payments: int
    months_paid: list[date]
    months_missed: list[date]
    months_split: list[date]  # more than one payment in the month, adding up to about one EMI
    bounces: int
    notes: list[str] = field(default_factory=list)


def _month(d: date) -> date:
    return d.replace(day=1)


def _months_between(a: date, b: date) -> list[date]:
    out, m = [], _month(a)
    while m <= _month(b):
        out.append(m)
        m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def usual_emi(pays: list[Transaction]) -> Decimal | None:
    """The usual payment: the most common amount if it repeats; otherwise the most common
    monthly total (an EMI collected in pieces when the balance ran short)."""
    if len(pays) < 2:
        return None
    top, times = Counter(t.debit for t in pays).most_common(1)[0]
    if times >= 2 and times >= 0.4 * len(pays):
        return top
    monthly: dict[date, Decimal] = {}
    for t in pays:
        monthly[_month(t.date)] = monthly.get(_month(t.date), ZERO) + t.debit
    total, n = Counter(monthly.values()).most_common(1)[0]
    if n >= 2:
        return total
    return sorted(monthly.values())[len(monthly) // 2]  # median month


def build_loans(transactions: list[Transaction], returns: ReturnsSection) -> list[LenderLoan]:
    by: dict[str, list[Transaction]] = {}
    for t in transactions:
        if t.lender:
            by.setdefault(t.lender, []).append(t)

    bounced_originals = {id(b.original) for b in returns.bounces if b.original is not None}
    loans = []
    for lender, entries in by.items():
        entries.sort(key=lambda t: t.date)
        pays = [t for t in entries if t.debit]
        gets = [t for t in entries if t.credit]
        paid_months = sorted({_month(t.date) for t in pays})
        emi = usual_emi(pays)

        missed, split = [], []
        if len(paid_months) >= 2:
            missed = [m for m in _months_between(paid_months[0], paid_months[-1]) if m not in paid_months]
        if emi:
            for m in paid_months:
                in_month = [t.debit for t in pays if _month(t.date) == m]
                if len(in_month) >= 2 and all(a < emi for a in in_month):
                    split.append(m)

        loan = LenderLoan(
            lender=lender, type=entries[0].lender_type, entries=entries, emi=emi,
            paid_total=sum((t.debit for t in pays), ZERO),
            received_total=sum((t.credit for t in gets), ZERO),
            payments=len(pays), months_paid=paid_months, months_missed=missed, months_split=split,
            bounces=sum(1 for t in entries if id(t) in bounced_originals),
        )
        loans.append(loan)
    loans.sort(key=lambda x: (-(x.paid_total + x.received_total), x.lender))
    return loans
