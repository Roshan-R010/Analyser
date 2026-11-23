"""Cheque-wise list: every transaction with a cheque number, sorted by number."""
from __future__ import annotations

from analyser.model import Transaction


def build_cheque_list(transactions: list[Transaction]) -> list[Transaction]:
    chq = [t for t in transactions if t.cheque_no]
    return sorted(chq, key=lambda t: (int(t.cheque_no) if t.cheque_no.isdigit() else 10**12, t.date))
