"""Cheque / ECS returns (bounces), their reasons and charges; transfer returns kept apart.

One bounce = one row, even when the bank prints two lines for it. Each bounce is
counted in the month it happened. A return charge whose bounce isn't in the
statement ("Chq rtn chg Jan-26") still counts, in the month it names.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from analyser.enrich.modes import CHARGES, RETURN
from analyser.model import ZERO, Transaction

FUNDS, TECHNICAL, UNKNOWN = "Funds", "Technical", "Unknown"
ISSUED, DEPOSITED = "Issued by borrower", "Deposited by borrower"

TRANSFER_RETURN = re.compile(r"\b(rtgs|neft|imps)[\s\-/]*(rtn|return|rej)|\brvsl\b|\brevers"
                             r"|\bupi[\s\-]*rev\b", re.I)
CHARGE_FOR_RETURN = re.compile(r"\brtn\b|return|\bret\b|bounce|dishon|\bsc\s*:", re.I)
CHARGE_MONTH = re.compile(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s\-']*(\d{2,4})", re.I)
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

# (pattern, readable reason, kind)
REASONS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"insuf|no[_\s]*funds|funds?\s*(not\s*)?avail|exceeds\s*arrang|balance\s*insuf", re.I),
     "Funds insufficient", FUNDS),
    (re.compile(r"refer\s*to\s*drawer", re.I), "Refer to drawer", FUNDS),
    (re.compile(r"stop(ped)?\s*(pay|by)|payment\s*stop", re.I), "Payment stopped by drawer", TECHNICAL),
    (re.compile(r"a/?c(count)?\s*clos|closed", re.I), "Account closed", TECHNICAL),
    (re.compile(r"sign", re.I), "Signature differs", TECHNICAL),
    (re.compile(r"already\s*paid|chq_already", re.I), "Already paid", TECHNICAL),
    (re.compile(r"stale|post[\s\-]*dated|out\s*of\s*date", re.I), "Date problem", TECHNICAL),
    (re.compile(r"(incorrect|invalid|wrong)\s*(a/?c|account)|no\s*such\s*account|account\s*does\s*not\s*exist"
                r"|unknown\s*account|unknow\b", re.I), "Incorrect account", TECHNICAL),
    (re.compile(r"alter|mismatch|differ|incorrect|invalid|not\s*arranged|frozen|block|dormant", re.I),
     "Details mismatch", TECHNICAL),
    (re.compile(r"mandate|umrn|not\s*registered", re.I), "Mandate problem", TECHNICAL),
]


@dataclass
class Bounce:
    date: date
    month: date  # first day of the month it is counted in
    description: str
    cheque_no: str
    amount: Decimal
    credit: Decimal
    debit: Decimal
    balance: Decimal | None
    reason: str
    kind: str  # Funds / Technical / Unknown
    direction: str  # Issued by borrower / Deposited by borrower / ""
    entries: list[Transaction] = field(default_factory=list)  # the return line(s)
    original: Transaction | None = None  # the payment that bounced
    charges: list[Transaction] = field(default_factory=list)
    note: str = ""

    @property
    def charge_total(self) -> Decimal:
        return sum((c.debit for c in self.charges), ZERO)


@dataclass
class TransferReturn:
    txn: Transaction
    reason: str


@dataclass
class ReturnsSection:
    bounces: list[Bounce]
    transfer_returns: list[TransferReturn]

    def count_by_month(self) -> dict[date, int]:
        out: dict[date, int] = {}
        for b in self.bounces:
            out[b.month] = out.get(b.month, 0) + 1
        return out


def _month(d: date) -> date:
    return d.replace(day=1)


def _reason(text: str) -> tuple[str, str]:
    for pat, label, kind in REASONS:
        if pat.search(text):
            return label, kind
    return "", UNKNOWN


def build_returns(transactions: list[Transaction]) -> ReturnsSection:
    bounces: list[Bounce] = []
    transfers: list[TransferReturn] = []

    for i, t in enumerate(transactions):
        if t.mode != RETURN:
            continue
        if TRANSFER_RETURN.search(t.description):
            label, _ = _reason(t.description)
            transfers.append(TransferReturn(txn=t, reason=label or ("Reversal" if re.search(
                r"rvsl|revers", t.description, re.I) else "")))
            continue
        # Same cheque, same day: the bank printed one bounce on two lines
        same = next((b for b in bounces if b.date == t.date and (
            (t.cheque_no and b.cheque_no == t.cheque_no) or
            (not t.cheque_no and b.amount == (t.credit or t.debit)))), None)
        if same:
            same.entries.append(t)
            if not same.reason:
                same.reason, same.kind = _reason(t.description)
            continue
        label, kind = _reason(t.description)
        b = Bounce(date=t.date, month=_month(t.date), description=t.description, cheque_no=t.cheque_no,
                   amount=t.credit or t.debit, credit=t.credit, debit=t.debit, balance=t.balance,
                   reason=label, kind=kind, direction=ISSUED if t.credit else DEPOSITED, entries=[t])
        b.original = _find_original(transactions, i, b)
        bounces.append(b)

    _attach_charges(transactions, bounces)
    bounces.sort(key=lambda b: (b.date, b.cheque_no))
    return ReturnsSection(bounces=bounces, transfer_returns=transfers)


def _find_original(transactions: list[Transaction], i: int, b: Bounce) -> Transaction | None:
    """The payment that bounced: same amount, opposite side, shortly before."""
    t = transactions[i]
    best = None
    for j in range(i - 1, -1, -1):
        o = transactions[j]
        if o.date < t.date - timedelta(days=15):
            break
        if o.mode == RETURN:
            continue
        amount = o.debit if b.direction == ISSUED else o.credit
        if amount != b.amount:
            continue
        if b.cheque_no and o.cheque_no == b.cheque_no:
            return o
        best = best or o
    return best


def _charge_month(text: str) -> date | None:
    m = CHARGE_MONTH.search(text)
    if not m:
        return None
    y = int(m.group(2))
    y = y + 2000 if y < 100 else y
    return date(y, _MONTHS.index(m.group(1)[:3].lower()) + 1, 1)


def _attach_charges(transactions: list[Transaction], bounces: list[Bounce]) -> None:
    for c in transactions:
        if c.mode != CHARGES or not c.debit or not CHARGE_FOR_RETURN.search(c.description):
            continue
        # 1. Same cheque number
        target = next((b for b in bounces if c.cheque_no and b.cheque_no == c.cheque_no), None)
        # 2. The charge names a month ("Chq rtn chg Jan-26")
        named = _charge_month(c.description)
        if target is None and named:
            target = next((b for b in bounces if b.month == named and not b.charges), None)
        # 3. A bounce in the few days before the charge
        if target is None and not named:
            target = next((b for b in reversed(bounces)
                           if timedelta(0) <= c.date - b.date <= timedelta(days=5) and not b.charges), None)
        if target is not None:
            target.charges.append(c)
            continue
        # The bounce itself isn't in the statement: the charge is the only evidence
        month = named or _month(c.date)
        bounces.append(Bounce(
            date=c.date, month=month, description=c.description, cheque_no=c.cheque_no,
            amount=ZERO, credit=ZERO, debit=ZERO, balance=c.balance, reason="", kind=UNKNOWN,
            direction="", charges=[c],
            note=f"Only the return charge is in the statement; the bounce was in {month:%b %Y}"))
