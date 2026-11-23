"""Cashflow summary: one row per month, then Total, Monthly avg and Last 3/6/9/12 months.

Avg balance = average of every calendar day's closing balance within the statement
period (days before the first transaction use the opening balance). With several
accounts, each day's balances are added up. Summary rows average the monthly figures.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from analyser.combine import Account
from analyser.model import ZERO


@dataclass
class CashflowRow:
    label: str
    credit: Decimal
    debit: Decimal
    avg_balance: Decimal
    cr_entries: Decimal  # Decimal so monthly averages can be shown as-is
    dr_entries: Decimal
    returns: int | None  # None on summary rows
    month: date | None = None  # set on month rows

    @property
    def net(self) -> Decimal:
        return self.credit - self.debit


@dataclass
class CashflowSection:
    months: list[CashflowRow]
    total: CashflowRow
    monthly_avg: CashflowRow
    last: dict[int, CashflowRow | None]  # 3/6/9/12 -> row, or None when not enough months


def _month(d: date) -> date:
    return d.replace(day=1)


def _next_month(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def daily_balances(acc: Account) -> dict[date, Decimal]:
    """Closing balance for every day of the account's period."""
    if not acc.transactions:
        return {}
    start = acc.period_from or acc.transactions[0].date
    end = acc.period_to or acc.transactions[-1].date
    end = max(end, acc.transactions[-1].date)
    start = min(start, acc.transactions[0].date)
    closing: dict[date, Decimal] = {}
    for t in acc.transactions:
        if t.balance is not None:
            closing[t.date] = t.balance  # last entry of the day wins
    out = {}
    bal = acc.opening_balance if acc.opening_balance is not None else ZERO
    d = start
    while d <= end:
        bal = closing.get(d, bal)
        out[d] = bal
        d += timedelta(days=1)
    return out


def build_cashflow(accounts: list[Account], returns_by_month: dict[date, int] | None = None) -> CashflowSection:
    returns_by_month = returns_by_month or {}
    # Sum of all accounts' balances for each day any account covers
    day_total: dict[date, Decimal] = {}
    for acc in accounts:
        for d, b in daily_balances(acc).items():
            day_total[d] = day_total.get(d, ZERO) + b

    tx = [t for acc in accounts for t in acc.transactions]
    if not tx and not day_total:
        empty = CashflowRow("Total", ZERO, ZERO, ZERO, Decimal(0), Decimal(0), None)
        return CashflowSection([], empty, empty, {3: None, 6: None, 9: None, 12: None})

    first = _month(min(list(day_total) + [t.date for t in tx]))
    last = _month(max(list(day_total) + [t.date for t in tx]))
    rows: list[CashflowRow] = []
    m = first
    while m <= last:
        mt = [t for t in tx if _month(t.date) == m]
        days = [b for d, b in day_total.items() if _month(d) == m]
        rows.append(CashflowRow(
            label=f"{m:%b %Y}",
            credit=sum((t.credit for t in mt), ZERO),
            debit=sum((t.debit for t in mt), ZERO),
            avg_balance=(sum(days, ZERO) / len(days)) if days else ZERO,
            cr_entries=Decimal(sum(1 for t in mt if t.credit)),
            dr_entries=Decimal(sum(1 for t in mt if t.debit)),
            returns=returns_by_month.get(m, 0),
            month=m,
        ))
        m = _next_month(m)

    total = _summary(f"Total ({rows[0].label} - {rows[-1].label})", rows, average=False)
    avg = _summary(f"Monthly Avg. ({rows[0].label} - {rows[-1].label})", rows, average=True)
    last_n = {}
    for n in (3, 6, 9, 12):
        if len(rows) < n:
            last_n[n] = None
        else:
            part = rows[-n:]
            last_n[n] = _summary(f"Last {n} months ({part[0].label} to {part[-1].label})", part, average=False)
    return CashflowSection(months=rows, total=total, monthly_avg=avg, last=last_n)


def _summary(label: str, rows: list[CashflowRow], average: bool) -> CashflowRow:
    n = Decimal(len(rows))
    credit = sum((r.credit for r in rows), ZERO)
    debit = sum((r.debit for r in rows), ZERO)
    cr = sum((r.cr_entries for r in rows), Decimal(0))
    dr = sum((r.dr_entries for r in rows), Decimal(0))
    avg_bal = sum((r.avg_balance for r in rows), ZERO) / n
    if average:
        credit, debit, cr, dr = credit / n, debit / n, cr / n, dr / n
    return CashflowRow(label=label, credit=credit, debit=debit, avg_balance=avg_bal,
                       cr_entries=cr, dr_entries=dr, returns=None)


def rupees(x: Decimal) -> Decimal:
    """Round to whole rupees for display (half up)."""
    return x.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
