"""Loans: every entry with a lender, grouped by lender, with one summary line each.

Summary per lender: type, usual EMI, months paid, months missed between the first and
last payment, months paid in pieces, bounced payments, and money received (disbursements).
"""
from __future__ import annotations

import re
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


# ---------------------------------------------------------------- report wording
_MANDATE = re.compile(r"^(?P<who>.+?)\s*\(mandate\s+(?P<ref>[A-Z0-9]+)\)\s*$", re.I)
_BANK_LOAN = re.compile(r"\bloan\s+a/c\b", re.I)
_PLAIN_TYPES = {"Bank", "Lender not named", "Chit fund"}  # already clear from the name / wording


@dataclass
class LoanBlock:
    """One lender (or one mandate) as shown on the loan page."""
    title: str
    subline: str
    paid: Decimal
    received: Decimal
    rows: list[tuple[Transaction, str]]  # (entry, what it is)


def _short_refs(refs: list[str]) -> dict[str, str]:
    """4 characters that tell the mandates apart. Refs often end alike (a shared date tail),
    so that shared tail is skipped: ...04695702202606 / ...04696840202606 -> 5702 / 6840."""
    refs = sorted(set(refs))
    tail = 0
    if len(refs) > 1:
        while tail < min(map(len, refs)) and len({r[len(r) - tail - 1] for r in refs}) == 1:
            tail += 1
    out = {}
    for r in refs:
        core = r[:len(r) - tail] if len(r) - tail >= 4 else r
        out[r] = core[-4:]
    if len(set(out.values())) < len(out):  # still clashing: longest needed plain tail
        for r in refs:
            n = 4
            while n < len(r) and any(o != r and o.endswith(r[-n:]) for o in refs):
                n += 1
            out[r] = r[-n:]
    return out


def _and(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _title(s: str) -> str:
    return s.title() if s.isupper() else s


def loan_blocks(loans: list[LenderLoan]) -> list[LoanBlock]:
    refs = [m.group("ref") for ln in loans if (m := _MANDATE.match(ln.lender))]
    short = _short_refs(refs)
    blocks = []
    for ln in loans:
        m = _MANDATE.match(ln.lender)
        mandate = bool(m)
        if m:
            title = f"{m.group('who')} · mandate …{short[m.group('ref')]}"
        else:
            title = _title(ln.lender)
        bank_loan = bool(_BANK_LOAN.search(ln.lender))
        installment = ln.lender == "Auto-debit installment"
        chit = ln.type == "Chit fund"

        rows, extra = [], 0
        for t in ln.entries:
            if t.credit:
                what = "Loan amount received"
            elif chit:
                what = "Chit fund payment"
            elif mandate:
                regular = ln.emi is None or t.debit == ln.emi
                extra += not regular
                what = "Monthly auto-debit" if regular else "Additional auto-debit"
            elif installment:
                what = "Monthly installment"
            elif bank_loan or (ln.emi and t.debit == ln.emi):
                what = "EMI payment"
            else:
                what = f"Payment · {t.mode}"
            rows.append((t, what))

        n = ln.payments
        bits = [] if ln.type in _PLAIN_TYPES else [ln.type]
        bits.append(f"{n} payment{'s' if n != 1 else ''}")
        if ln.months_split:
            bits.append(f"split EMI entries in {_and([f'{x:%B}' for x in ln.months_split])}")
        elif chit:
            bits.append("transfer to chit fund" if any(t.mode == "Transfer" for t in ln.entries if t.debit)
                        else "chit fund payment")
        elif mandate:
            bits.append("monthly auto-debit" + (f" and {'one' if extra == 1 else extra} additional debit"
                                                f"{'s' if extra > 1 else ''}" if extra else ""))
        elif installment:
            bits.append("ACH installment")
        elif bank_loan:
            bits.append("EMI installment")
        if ln.months_missed:
            bits.append("no payment in " + _and([f"{x:%b %Y}" for x in ln.months_missed]))
        if ln.received_total:
            bits.append(f"₹{_inr(ln.received_total)} received from this lender")
        blocks.append(LoanBlock(title=title, subline=" · ".join(bits) if n else " · ".join(bits[1:] or bits),
                                paid=ln.paid_total, received=ln.received_total, rows=rows))
    return blocks


def _inr(x: Decimal) -> str:
    from analyser.sections.flags import inr
    return inr(x)
