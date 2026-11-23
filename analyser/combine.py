"""Combine several statements of one borrower.

Statements of the same account (same bank + account number) are joined into one
running list: overlapping days are counted once, and a gap between statements
is reported. Different accounts stay separate.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from analyser.model import Statement, Transaction


@dataclass
class Account:
    bank: str
    account_no: str
    holder: str
    statements: list[Statement]
    transactions: list[Transaction] = field(default_factory=list)
    opening_balance: Decimal | None = None
    period_from: date | None = None
    period_to: date | None = None
    notes: list[str] = field(default_factory=list)  # gaps, overlaps, mismatches


def _key(t: Transaction):
    return (t.date, t.debit, t.credit, t.balance)


def combine(statements: list[Statement]) -> list[Account]:
    groups: dict[tuple, list[Statement]] = {}
    for st in statements:
        # Without an account number we can't be sure two statements are the same account
        k = (st.bank, st.account_no) if st.account_no else (st.bank, f"#{st.statement_no}")
        groups.setdefault(k, []).append(st)

    accounts = []
    for (bank, acc_no), sts in groups.items():
        sts.sort(key=lambda s: (s.period_from or date.min))
        acc = Account(bank=bank, account_no=acc_no if not acc_no.startswith("#") else "",
                      holder=next((s.account_holder for s in sts if s.account_holder), ""),
                      statements=sts)
        acc.opening_balance = sts[0].opening_balance
        acc.period_from = sts[0].period_from
        for st in sts:
            _append(acc, st)
        accounts.append(acc)
    return accounts


def _append(acc: Account, st: Statement) -> None:
    if not acc.transactions:
        acc.transactions = list(st.transactions)
        acc.period_to = st.period_to
        return
    last_date = acc.transactions[-1].date
    # Transactions of the new statement on days already covered are duplicates
    # if an identical entry (date, amounts, balance) is already there.
    seen = Counter(_key(t) for t in acc.transactions if t.date >= (st.period_from or date.min))
    dropped = 0
    for t in st.transactions:
        if t.date <= last_date and seen[_key(t)] > 0:
            seen[_key(t)] -= 1
            dropped += 1
            continue
        acc.transactions.append(t)
    if dropped:
        acc.notes.append(f"Statement {st.statement_no} overlaps the previous one: "
                         f"{dropped} repeated entries counted once")
    prev_end = acc.period_to
    if prev_end and st.period_from and st.period_from > prev_end + timedelta(days=1):
        acc.notes.append(f"Gap: no statement covers {prev_end + timedelta(days=1)} "
                         f"to {st.period_from - timedelta(days=1)}")
    acc.period_to = max(filter(None, [acc.period_to, st.period_to]), default=None)
