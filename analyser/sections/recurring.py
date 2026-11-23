"""Recurring debits: the same party paid again and again.

A party is listed with at least 3 payments spread over at least 2 months (and
Rs 10,000+ in total, unless it is a lender). Cash, own-account transfers, charges and
unknown entries are not "recurring payments".

Inside each party, payments are grouped by amount (and by mandate, for auto-debits):
- an amount paid 3+ times gets its own line (2+ for a mandate or loan account, or when
  the party has only a few payments; at most 5 such lines per party); near-equal amounts (within 0.5%) join it
  and are listed as the odd ones ("30,000 x 3 / 30,010.50 x 1 (14 Oct)");
- one or two one-off amounts next to repeated ones are "Additional payment" lines;
- otherwise the one-offs share a single "Variable amounts" line.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from analyser.model import ZERO, Transaction

EXCLUDE = {"_CASH", "_SELF", "_CHARGES", "_INTEREST", "_RETURNS", "_UNKNOWN"}
MIN_PAYMENTS = 3
MIN_MONTHS = 2
MIN_TOTAL = Decimal("10000")  # smaller repeat spends (fuel, food) only lengthen the report
NEAR = Decimal("0.005")  # amounts within 0.5% of a repeated amount join it
MAX_EXTRA_LINES = 2  # more one-offs than this are shown as one "Variable amounts" line
MIN_REPEAT = 3  # times an amount must recur for its own line (2 for mandates, loans, or small parties)
SMALL_PARTY = 6  # payments; up to this many, an amount paid twice already counts as repeated
MAX_AMOUNT_LINES = 5  # busy parties: the rest go into "Variable amounts"

MANDATE = re.compile(r"mandate\s+([A-Z0-9]+)", re.I)
BANK_LOAN = re.compile(r"^(?P<bank>.+?)\s+loan\s+(?P<acc>a/c\s*\S+)$", re.I)


@dataclass
class AmountLine:
    amount: Decimal | None  # None = "Variable amounts"
    count: int
    total: Decimal
    dates: list[date]
    pattern: str
    note: str = ""  # "Mandate · …111122223333", "XYZ Bank loan · a/c …1234"
    odd: list[tuple[Decimal, date]] = field(default_factory=list)  # near-equal amounts in this line

    @property
    def main_count(self) -> int:
        return self.count - len(self.odd)


@dataclass
class RecurringRow:
    party: str
    key: str
    description: str  # a typical description
    total: Decimal
    entries: int
    amounts: list[tuple[Decimal, int]]  # (amount, times), most common first
    interval: str
    dates: list[date]
    lender: str
    lines: list[AmountLine] = field(default_factory=list)


def interval_label(dates: list[date]) -> str:
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    if not gaps:
        return "-"
    months = len({d.replace(day=1) for d in dates})
    per_month = len(dates) / months
    if per_month >= 4:
        return f"Frequent (~{per_month:.0f}/month)"
    g = statistics.median(gaps)
    spread = statistics.pstdev(gaps) if len(gaps) > 1 else 0
    if g <= 2:
        label = "Daily"
    elif 5 <= g <= 9:
        label = "Weekly"
    elif 12 <= g <= 18:
        label = "Fortnightly"
    elif 25 <= g <= 35:
        label = "Monthly"
    elif 80 <= g <= 100:
        label = "Quarterly"
    else:
        return "Irregular"
    # Mostly irregular gaps around that median: say so
    return label if spread <= max(4, g * 0.5) else "Irregular"


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def pattern_label(dates: list[date], fixed_amount: bool) -> str:
    """What the payment dates show. Every gap must fit, not just the typical one."""
    if len(dates) < 2:
        return "Additional payment"
    ds = sorted(dates)
    gaps = [(b - a).days for a, b in zip(ds, ds[1:])]
    months = [d.replace(day=1) for d in ds]
    if all(25 <= g <= 35 for g in gaps) and len(set(months)) == len(months):
        day, times = Counter(d.day for d in ds).most_common(1)[0]
        # Same day in most months; a holiday can only push the debit a few days later
        if times * 2 >= len(ds) and all(0 <= d.day - day <= 3 for d in ds):
            return f"Monthly · {_ordinal(day)}"
        return "About monthly"
    if all(20 <= g <= 40 for g in gaps):
        return "About monthly"
    if all(10 <= g <= 20 for g in gaps):
        return "About fortnightly"
    if all(5 <= g <= 9 for g in gaps):
        return "About weekly"
    if all(80 <= g <= 100 for g in gaps):
        return "About quarterly"
    return "Variable dates" if fixed_amount else "Irregular"


def _note(t: Transaction, party: str) -> str:
    if not t.lender:
        return ""
    m = MANDATE.search(t.lender)
    if m:
        ref = m.group(1)
        return f"Mandate · …{ref[-12:]}" if len(ref) > 12 else f"Mandate · {ref}"
    m = BANK_LOAN.match(t.lender)
    if m:
        return f"{m.group('bank')} loan · {m.group('acc')}"
    return "" if t.lender.lower() == party.lower() else t.lender


def amount_lines(tx: list[Transaction], party: str) -> list[AmountLine]:
    """Group one party's payments into lines (see the module notes)."""
    tx = sorted(tx, key=lambda t: t.date)
    by: dict[tuple[str, Decimal], list[Transaction]] = {}
    for t in tx:
        by.setdefault((_note(t, party), t.debit), []).append(t)
    def enough(k, v) -> bool:
        return len(v) >= MIN_REPEAT or (len(v) >= 2 and (k[0] or len(tx) <= SMALL_PARTY))
    ranked = sorted((k for k, v in by.items() if enough(k, v)),
                    key=lambda k: (-len(by[k]), -sum(t.debit for t in by[k])))
    repeated = {k: by[k] for k in ranked[:MAX_AMOUNT_LINES]}
    singles = sorted((t for k, v in by.items() if k not in repeated for t in v), key=lambda t: t.date)

    # Near-equal one-offs join the repeated amount they sit next to
    odd: dict[tuple[str, Decimal], list[Transaction]] = {}
    left = []
    for t in singles:
        home = next((k for k in repeated
                     if k[0] == _note(t, party) and abs(t.debit - k[1]) <= k[1] * NEAR), None)
        if home:
            odd.setdefault(home, []).append(t)
        else:
            left.append(t)

    lines = []
    for k, v in repeated.items():
        extra = odd.get(k, [])
        all_tx = sorted(v + extra, key=lambda t: t.date)
        ds = [t.date for t in all_tx]
        lines.append(AmountLine(
            amount=k[1], count=len(all_tx), total=sum((t.debit for t in all_tx), ZERO),
            dates=ds, pattern=pattern_label(ds, True), note=k[0],
            odd=[(t.debit, t.date) for t in extra]))
    lines.sort(key=lambda ln: (ln.dates[0], -ln.count, -ln.amount))

    if left and lines and len(left) <= MAX_EXTRA_LINES:
        for t in left:
            lines.append(AmountLine(amount=t.debit, count=1, total=t.debit, dates=[t.date],
                                    pattern="Additional payment", note=_note(t, party)))
    elif left:
        notes = {_note(t, party) for t in left}
        ds = [t.date for t in left]
        lines.append(AmountLine(
            amount=None, count=len(left), total=sum((t.debit for t in left), ZERO),
            dates=ds, pattern=pattern_label(ds, False), note=notes.pop() if len(notes) == 1 else ""))
    return lines


def build_recurring(transactions: list[Transaction]) -> list[RecurringRow]:
    by: dict[str, list[Transaction]] = {}
    for t in transactions:
        if t.debit and t.party_key not in EXCLUDE:
            by.setdefault(t.party_key, []).append(t)
    rows = []
    for key, tx in by.items():
        tx.sort(key=lambda t: t.date)
        months = {t.date.replace(day=1) for t in tx}
        total = sum((t.debit for t in tx), ZERO)
        is_lender = any(t.lender for t in tx)
        if len(tx) < MIN_PAYMENTS or len(months) < MIN_MONTHS or (total < MIN_TOTAL and not is_lender):
            continue
        party = tx[0].party_clean
        rows.append(RecurringRow(
            party=party, key=key,
            description=Counter(t.description for t in tx).most_common(1)[0][0],
            total=total, entries=len(tx), amounts=Counter(t.debit for t in tx).most_common(),
            interval=interval_label([t.date for t in tx]), dates=[t.date for t in tx],
            lender=next((t.lender for t in tx if t.lender), ""),
            lines=amount_lines(tx, party),
        ))
    rows.sort(key=lambda r: (-r.total, r.party))
    return rows
