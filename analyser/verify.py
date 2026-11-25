"""Balance check: the gate that decides whether a statement was read correctly.

Every row must satisfy: previous balance + credit - debit = this row's balance.
If the bank prints its own totals, ours must match them too.
A statement that fails is never reported as if its numbers were right.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from analyser.model import ZERO, Statement


@dataclass
class BalanceBreak:
    index: int  # position in statement.transactions
    page_no: int
    date: str
    description: str
    expected: Decimal  # previous balance + credit - debit
    printed: Decimal | None  # balance printed on the statement


@dataclass
class VerifyResult:
    rows_checked: int = 0
    breaks: list[BalanceBreak] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # totals mismatches etc.

    @property
    def ok(self) -> bool:
        return not self.breaks and not self.problems and self.rows_checked > 0


def verify(st: Statement) -> VerifyResult:
    res = VerifyResult()
    if not st.transactions:
        res.problems.append("No transactions were read")
        return res
    if st.opening_balance is None:
        res.problems.append("Opening balance unknown")
        return res

    prev = st.opening_balance
    for i, t in enumerate(st.transactions):
        expected = prev + t.credit - t.debit
        res.rows_checked += 1
        if t.balance is None:
            res.breaks.append(_brk(i, t, expected, None))
            prev = expected
            continue
        if t.balance == -expected and expected < 0:
            # Some banks print an overdrawn balance without its minus sign (Indian Bank): the row is
            # right, the printed sign is missing. Keep the true negative balance.
            t.balance = expected
        elif t.balance != expected:
            res.breaks.append(_brk(i, t, expected, t.balance))
        prev = t.balance  # carry on from the printed balance so one bad row = one break

    total_dr = sum((t.debit for t in st.transactions), ZERO)
    total_cr = sum((t.credit for t in st.transactions), ZERO)
    # A bank may net a reversal off the column it was printed in rather than add it to the other
    ok_dr = {total_dr, total_dr - st.reversal_total}
    ok_cr = {total_cr, total_cr - st.reversal_total}
    if st.printed_total_debit is not None and st.printed_total_debit not in ok_dr:
        res.problems.append(f"Total debit read {total_dr} but statement prints {st.printed_total_debit}")
    if st.printed_total_credit is not None and st.printed_total_credit not in ok_cr:
        res.problems.append(f"Total credit read {total_cr} but statement prints {st.printed_total_credit}")
    if st.printed_opening is not None and st.printed_opening != st.opening_balance:
        res.problems.append(f"Opening balance worked out as {st.opening_balance} "
                            f"but statement prints {st.printed_opening}")
    last = st.transactions[-1].balance
    if st.printed_closing is not None and last is not None and st.printed_closing != last:
        res.problems.append(f"Closing balance read {last} but statement prints {st.printed_closing}")
    return res


def printed_checks(st: Statement) -> list[str]:
    """Which of the bank's own printed figures were matched (for the report's checks list)."""
    out = []
    if st.printed_total_debit is not None or st.printed_total_credit is not None:
        out.append("totals")
    if st.printed_opening is not None:
        out.append("opening")
    if st.printed_closing is not None:
        out.append("closing balance")
    return out


def _brk(i, t, expected, printed) -> BalanceBreak:
    return BalanceBreak(index=i, page_no=t.page_no, date=t.date.isoformat(),
                        description=t.description[:80], expected=expected, printed=printed)
