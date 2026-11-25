"""Statements whose own numbers don't add up: what is wrong and exactly where.

A statement in a layout we know (a bank profile read it) but whose balances or printed totals
fail the check is still reported, marked SUSPICIOUS. For each statement this lists the entries
where the running balance stops following from the entry before, with the page, and what
that pattern usually means. It can also be a layout detail we read wrongly, so the wording
says "compare with the original" rather than accusing anyone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


MAX_FINDINGS = 8  # places listed per statement; the count of the rest is still shown
MANY_BREAKS = 3  # this many broken rows (or a printed-total mismatch) makes it "highly" suspicious


@dataclass
class Finding:
    page_no: int
    date: date
    description: str
    previous: Decimal | None  # balance before this entry (as printed on the row before)
    debit: Decimal
    credit: Decimal
    expected: Decimal  # previous balance + credit - debit
    printed: Decimal | None  # balance the statement prints on this row
    hint: str

    @property
    def difference(self) -> Decimal | None:
        return None if self.printed is None else abs(self.printed - self.expected)


@dataclass
class SuspiciousStatement:
    statement_no: int
    bank: str
    file_name: str
    rows: int
    breaks: int
    level: str  # "high" or "watch"
    findings: list[Finding] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # printed totals / opening / closing that disagree
    what_might_be_wrong: list[str] = field(default_factory=list)

    @property
    def more(self) -> int:
        return max(0, self.breaks - len(self.findings))


def _hint(idx: int, t, prev_t, finding: Finding) -> str:
    if finding.printed is None:
        return "No balance is printed on this row."
    if idx == 0:
        return "The first entry does not follow from the opening balance."
    if prev_t is not None and prev_t.page_no != t.page_no:
        return f"First entry on page {t.page_no}: it does not follow the last entry of page {prev_t.page_no}."
    if finding.previous is not None and finding.printed == finding.previous + t.debit - t.credit and t.debit != t.credit:
        return "Looks like the debit and credit were swapped on this row."
    if finding.printed == finding.previous:
        return "The balance did not move although the entry has an amount."
    return "The balance printed here is not what the entries above it add up to."


def build_suspicion(loaded: list) -> list[SuspiciousStatement]:
    """One entry for each statement that failed its check but was still readable."""
    out = []
    for ls in loaded:
        if ls.check.ok:
            continue
        st, check = ls.statement, ls.check
        tx = st.transactions
        findings = []
        for b in check.breaks[:MAX_FINDINGS]:
            t = tx[b.index]
            prev_t = tx[b.index - 1] if b.index > 0 else None
            previous = b.expected - t.credit + t.debit
            f = Finding(page_no=t.page_no, date=t.date, description=t.description[:90], previous=previous,
                        debit=t.debit, credit=t.credit, expected=b.expected, printed=b.printed, hint="")
            f.hint = _hint(b.index, t, prev_t, f)
            findings.append(f)

        notes = []
        if check.breaks:
            isolated = len(check.breaks) < max(1, check.rows_checked // 50)
            notes.append(
                f"{len(check.breaks)} of {check.rows_checked} entries do not follow from the entry before them. "
                + ("Every other entry continues correctly, which fits a changed amount or balance on those entries, "
                   "or entries removed at that point." if isolated else
                   "That many is more than a single edit: the statement may have been rewritten in several places."))
        if any(b.printed is None for b in check.breaks):
            notes.append("Some rows print no balance, so they cannot be checked.")
        for p in check.problems:
            if "Total debit" in p or "Total credit" in p:
                notes.append("The bank's own printed totals differ from the sum of the entries: entries may have "
                             "been added, removed or changed.")
                break
        notes.append("It can also be a detail of this bank's layout that we read wrongly. Compare the places "
                     "listed here with the original statement.")
        high = len(check.breaks) >= MANY_BREAKS or any("Total" in p for p in check.problems)
        out.append(SuspiciousStatement(
            statement_no=st.statement_no, bank=st.bank, file_name=ls.file_name, rows=check.rows_checked,
            breaks=len(check.breaks), level="high" if high else "watch", findings=findings,
            problems=list(check.problems), what_might_be_wrong=notes))
    return out



def suspicion_flag(s: SuspiciousStatement) -> str:
    """The one line for the flags list."""
    what = (f"{s.breaks} of {s.rows} entries do not follow from the balance before them" if s.breaks
            else "the bank's printed totals do not match the entries")
    where = f"; first at page {s.findings[0].page_no}, {s.findings[0].date:%d %b %Y}" if s.findings else ""
    return f"SUSPICIOUS: statement {s.statement_no} does not add up: {what}{where}"
