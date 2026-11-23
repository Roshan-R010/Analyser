"""Cross-checks: every total in the report is recomputed another way and compared.

A failed check is shown in the report with the exact numbers, never hidden.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from analyser.model import ZERO, Transaction
from analyser.verify import printed_checks


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def _eq(name: str, a: Decimal, b: Decimal, what_a: str, what_b: str) -> Check:
    return Check(name, a == b, "" if a == b else f"{what_a} {a} vs {what_b} {b}")


def build_checks(report) -> list[Check]:
    tx: list[Transaction] = report.transactions
    credits = sum((t.credit for t in tx), ZERO)
    debits = sum((t.debit for t in tx), ZERO)
    checks: list[Check] = []

    for s in report.statements:
        st, v = s.statement, s.check
        detail = f"{v.rows_checked} rows" if v.ok else f"{len(v.breaks)} breaks; {'; '.join(v.problems)}"
        matched = printed_checks(st)
        printed = f", matches the bank's printed {' and '.join(matched)}" if v.ok and matched else ""
        checks.append(Check(f"Statement {st.statement_no} ({st.bank.upper()}): every balance adds up", v.ok,
                            detail + printed))
    for acc, v in report.account_checks:
        checks.append(Check(f"Account ...{acc.account_no[-4:] or '?'}: statements join up", v.ok,
                            "" if v.ok else f"{len(v.breaks)} breaks at the joins"))

    cf = report.cashflow
    checks.append(_eq("Monthly credits add up to the total", sum((r.credit for r in cf.months), ZERO), credits,
                      "months", "transactions"))
    checks.append(_eq("Monthly debits add up to the total", sum((r.debit for r in cf.months), ZERO), debits,
                      "months", "transactions"))
    entries = sum((r.cr_entries + r.dr_entries for r in cf.months), Decimal(0))
    nonzero = sum(1 for t in tx if t.credit) + sum(1 for t in tx if t.debit)
    checks.append(Check("Entry counts match", entries == nonzero, f"{entries} vs {nonzero}" if entries != nonzero else ""))

    bad = []
    for mp in report.month_parties:
        c = sum((r.amount for r in mp.credits), ZERO)
        d = sum((r.amount for r in mp.debits), ZERO)
        if c != mp.credit_total or d != mp.debit_total:
            bad.append(f"{mp.month:%b %Y}: in {c} vs {mp.credit_total}, out {d} vs {mp.debit_total}")
    checks.append(Check("Counterparty totals add up to each month's totals", not bad, "; ".join(bad)))

    for label, rows, total in (("credit", report.modes_in, credits), ("debit", report.modes_out, debits)):
        amt = sum((r.amount for r in rows), ZERO)
        pct = sum((r.percent for r in rows), Decimal(0))
        ok = amt == total and (not rows or pct == Decimal("100.0"))
        checks.append(Check(f"Payment modes ({label}) cover everything and total 100%", ok,
                            "" if ok else f"amount {amt} vs {total}, percent {pct}"))

    loan_out = sum((ln.paid_total for ln in report.loans), ZERO)
    checks.append(Check("Loan payments are within total debits", loan_out <= debits, ""))
    return checks
