"""Short warning lines for the top of the report. Facts only, one line each."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from analyser.model import ZERO, Transaction
from analyser.sections.loans import LenderLoan
from analyser.sections.returns import FUNDS, TECHNICAL, ReturnsSection

LAKH = Decimal("100000")


@dataclass
class Flag:
    level: str  # "high" (red), "watch" (amber), "info"
    text: str


def inr(x: Decimal) -> str:
    """12,34,567 (whole rupees, Indian grouping)."""
    neg = x < 0
    s = str(abs(x).quantize(Decimal("1")))
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    out = ",".join(parts + [tail]) if parts else tail
    return ("-" if neg else "") + out


def _dates(ds: list[date]) -> str:
    return ", ".join(f"{d:%d %b}" for d in ds[:4]) + (f" +{len(ds) - 4} more" if len(ds) > 4 else "")


def build_flags(transactions: list[Transaction], daily: dict[date, Decimal], returns: ReturnsSection,
                loans: list[LenderLoan], notes: list[str]) -> list[Flag]:
    flags: list[Flag] = []
    credits = sum((t.credit for t in transactions), ZERO)
    debits = sum((t.debit for t in transactions), ZERO)

    funds = [b for b in returns.bounces if b.kind == FUNDS]
    tech = [b for b in returns.bounces if b.kind == TECHNICAL]
    charge_only = [b for b in returns.bounces if not b.entries and not b.amount]  # only a charge seen
    if funds:
        total = sum((b.amount for b in funds), ZERO)
        flags.append(Flag("high", f"{len(funds)} bounce(s) for insufficient funds"
                                  + (f", {inr(total)} in total" if total else "")
                                  + f": {_dates([b.date for b in funds])}"))
    if tech:
        flags.append(Flag("watch", f"{len(tech)} technical return(s): "
                                   + "; ".join(f"{b.date:%d %b} {b.reason.lower()}" for b in tech[:3])))
    own = [b for b in charge_only if b.direction == "Issued by borrower"]
    other = [b for b in charge_only if b.direction != "Issued by borrower"]
    if own:
        flags.append(Flag("high", f"{len(own)} of the borrower's own cheque(s) returned (charge only, "
                                  f"reason not shown): {', '.join(f'{b.date:%d %b %Y}' for b in own)}"))
    if other:
        def _what(b) -> str:
            who = " deposited cheque" if b.direction == "Deposited by borrower" else ""
            return f"{b.month:%b %Y}{who}"
        flags.append(Flag("watch", f"{len(other)} return charge(s) without the returned entry in the "
                                   f"statement ({', '.join(_what(b) for b in other)})"))

    neg_days = sorted(d for d, b in daily.items() if b < 0)
    if neg_days:
        low_day = min(daily, key=lambda d: daily[d])
        flags.append(Flag("high", f"Balance below zero on {len(neg_days)} day(s); lowest {inr(daily[low_day])} "
                                  f"on {low_day:%d %b %Y}"))

    paying = [ln for ln in loans if ln.payments]
    if paying:
        emi_total = sum((ln.emi for ln in paying if ln.emi), ZERO)
        flags.append(Flag("info", f"Paying {len(paying)} lender(s)"
                                  + (f"; usual EMIs add up to about {inr(emi_total)} a month" if emi_total else "")))
    for ln in loans:
        if ln.months_missed:
            flags.append(Flag("watch", f"{ln.lender}: no payment in {', '.join(f'{m:%b %Y}' for m in ln.months_missed[:4])}"))
        if ln.months_split:
            flags.append(Flag("watch", f"{ln.lender}: paid in pieces in {', '.join(f'{m:%b %Y}' for m in ln.months_split[:4])}"))
    received = [ln for ln in loans if ln.received_total]
    if received:
        flags.append(Flag("info", "Loan money received: " + "; ".join(
            f"{ln.lender} {inr(ln.received_total)}" for ln in received[:3])))

    if credits and debits:
        diff = abs(credits - debits) / credits
        avg_bal = (sum(daily.values(), ZERO) / len(daily)) if daily else ZERO
        months = max(1, len({d.replace(day=1) for d in daily}))
        if diff <= Decimal("0.02") and avg_bal < credits / months * Decimal("0.05"):
            flags.append(Flag("watch", f"Money out almost equals money in ({inr(debits)} out of {inr(credits)} in) "
                                       f"and little is kept: average balance {inr(avg_bal)}"))

    both: dict[str, list[Decimal]] = {}
    for t in transactions:
        if t.party_key.startswith("_"):
            continue
        both.setdefault(t.party_key, [ZERO, ZERO, t.party_clean])
        both[t.party_key][0] += t.credit
        both[t.party_key][1] += t.debit
    two_way = sorted(((v[2], v[0], v[1]) for v in both.values() if v[0] >= LAKH and v[1] >= LAKH),
                     key=lambda x: -(x[1] + x[2]))
    if two_way:
        flags.append(Flag("watch", "Same party pays in and is paid out: " + "; ".join(
            f"{n} (in {inr(c)}, out {inr(d)})" for n, c, d in two_way[:3])
            + (f" +{len(two_way) - 3} more" if len(two_way) > 3 else "")))

    cash_in = sum((t.credit for t in transactions if t.party_key == "_CASH"), ZERO)
    if credits and cash_in / credits >= Decimal("0.25"):
        flags.append(Flag("watch", f"Cash deposits are {cash_in * 100 / credits:.0f}% of money in ({inr(cash_in)})"))

    unknown_in = sum((t.credit for t in transactions if t.party_key == "_UNKNOWN"), ZERO)
    unknown_out = sum((t.debit for t in transactions if t.party_key == "_UNKNOWN"), ZERO)
    if (credits and unknown_in / credits > Decimal("0.10")) or (debits and unknown_out / debits > Decimal("0.10")):
        flags.append(Flag("info", f"Party not shown by the bank for {inr(unknown_in)} in and {inr(unknown_out)} out"))

    for n in notes:
        flags.append(Flag("watch", n))
    return flags
