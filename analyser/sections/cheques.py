"""Cheque-wise list: every cheque entry, in cheque-number order.

An entry belongs here when it has a cheque number, or when its mode says it is a cheque (a clearing
credit such as "CLG/<drawer>/<bank>" or a cheque the bank paid) even though the statement prints
no number for it: those come after the numbered ones, in date order, never left out.
"""
from __future__ import annotations

import re

from analyser.enrich.modes import CHEQUE, IMPS, NEFT, RETURN, RTGS, UPI
from analyser.model import Transaction

CHEQUE_TEXT = re.compile(r"chq|cheque|clg|clearing|\bcts\b", re.I)


ELECTRONIC = {NEFT, RTGS, IMPS, UPI}  # an instrument number printed on these is a transfer's, not a cheque's


def is_cheque_entry(t: Transaction) -> bool:
    if t.mode in ELECTRONIC:
        return False
    if t.cheque_no or t.mode == CHEQUE:
        return True
    return t.mode == RETURN and bool(CHEQUE_TEXT.search(t.description or ""))  # not NEFT/IMPS returns


def build_cheque_list(transactions: list[Transaction]) -> list[Transaction]:
    chq = [t for t in transactions if is_cheque_entry(t)]
    return sorted(chq, key=lambda t: (0 if t.cheque_no.isdigit() else 1, int(t.cheque_no) if t.cheque_no.isdigit() else 0, t.date))
