"""Cheque numbers for every cheque, wherever the bank puts them.

Most banks have a cheque column. Others put the number in the reference column
(KVB clearing: Ref No 000000000777) or inside the description
("RETURNED:900001:...", "INWARD CHEQUE RETURN SC :000000000555",
"CLG/ABC MOTORS/123456/KCU/..." for a deposited cheque).
"""
from __future__ import annotations

import re

from analyser.enrich.modes import CASH, CHARGES, CHEQUE, RETURN
from analyser.model import Transaction

_IN_DESCRIPTION = [
    re.compile(r"returned\s*:\s*(\d{3,10})\s*:", re.I),
    re.compile(r"\bsc\s*:\s*(\d{3,12})\b", re.I),
    re.compile(r"(?:chq|cheque)\s*(?:no\.?|number|#)\s*:?\s*(\d{3,10})\b", re.I),
    re.compile(r"^(\d{6}):cts", re.I),
    re.compile(r"^clg/[^/]+/(\d{6})/", re.I),  # deposited cheque: CLG/<drawer>/<chq no>/<bank>
]
# A reference that is really a cheque number: short, or long but mostly leading zeros
_CHEQUE_WORD = re.compile(r"chq|cheque|clg|clearing", re.I)
_REF_AS_CHEQUE = re.compile(r"^0*(\d{1,8})$")


def tidy(number: str) -> str:
    """Drop padding zeros: '000000000777' -> '777'. Keep at least one digit."""
    number = re.sub(r"\D", "", number or "")
    return number.lstrip("0") or ("0" if number else "")


def assign_cheques(transactions: list[Transaction]) -> None:
    for t in transactions:
        if t.cheque_no:
            t.cheque_no = tidy(t.cheque_no)
            continue
        for pat in _IN_DESCRIPTION:
            m = pat.search(t.description or "")
            if m:
                t.cheque_no = tidy(m.group(1))
                break
        if t.cheque_no:
            continue
        # Reference column holds the cheque number on cheque-type lines (e.g. KVB). Cash and charge lines
        # only count when they say cheque ("CHQ PAID-SELF", "CHQ RTN CHG"): an ATM or UPI reference is not one.
        if t.mode in (CHEQUE, RETURN) or (t.mode in (CHARGES, CASH) and _CHEQUE_WORD.search(t.description or "")):
            m = _REF_AS_CHEQUE.match((t.ref_no or "").strip())
            if m and (len(t.ref_no.strip()) <= 8 or t.ref_no.strip().startswith("0000")):
                t.cheque_no = tidy(m.group(1))
                if t.cheque_no == "0":  # an all-zero reference means none
                    t.cheque_no = ""
