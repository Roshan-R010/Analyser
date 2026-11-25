"""analyse(): checked statements in, every report section out.

Order: combine statements per account -> check the joins -> enrich (mode, cheque,
party, lender) -> returns -> cashflow -> parties -> loans -> recurring -> cheques ->
modes -> flags -> cross-checks.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from analyser.combine import Account, combine
from analyser.enrich import enrich
from analyser.enrich.parties import PartyIndex
from analyser.model import Statement, Transaction
from analyser.sections.cashflow import CashflowSection, build_cashflow, total_daily_balances
from analyser.sections.checks import Check, build_checks
from analyser.sections.cheques import build_cheque_list
from analyser.sections.flags import Flag, build_flags
from analyser.sections.loans import LenderLoan, build_loans
from analyser.sections.modes import ModeShare, build_mode_split
from analyser.sections.parties import MonthParties, UnknownSection, build_month_parties, build_unknown
from analyser.sections.recurring import RecurringRow, build_recurring
from analyser.sections.returns import ReturnsSection, build_returns
from analyser.sections.suspicion import SuspiciousStatement, build_suspicion, suspicion_flag
from analyser.verify import VerifyResult, verify


@dataclass
class Report:
    statements: list  # LoadedStatement, in upload order
    accounts: list[Account]
    account_checks: list[tuple[Account, VerifyResult]]
    transactions: list[Transaction]  # all accounts, date order
    parties: PartyIndex
    returns: ReturnsSection
    cashflow: CashflowSection
    month_parties: list[MonthParties]
    unknown: UnknownSection
    loans: list[LenderLoan]
    recurring: list[RecurringRow]
    cheques: list[Transaction]
    modes_in: list[ModeShare]
    modes_out: list[ModeShare]
    flags: list[Flag] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    suspicious: list[SuspiciousStatement] = field(default_factory=list)

    @property
    def borrower(self) -> str:
        names = [a.holder for a in self.accounts if a.holder]
        return names[0] if names else "Borrower"

    @property
    def all_checks_ok(self) -> bool:
        return all(c.ok for c in self.checks)


def analyse(loaded: list) -> Report:
    """`loaded` are LoadedStatement objects that are `reportable`: balance check passed, or a known layout
    whose numbers don't add up (reported as suspicious)."""
    for i, ls in enumerate(loaded, start=1):
        ls.statement.statement_no = i
        for t in ls.statement.transactions:
            t.statement_no = i
    accounts = combine([ls.statement for ls in loaded])
    account_checks = []
    suspect = {id(ls.statement) for ls in loaded if ls.suspicious}
    for acc in accounts:
        # Joins are only worth checking between statements that each add up
        if len(acc.statements) > 1 and not any(id(st) in suspect for st in acc.statements):
            joined = Statement(bank=acc.bank, opening_balance=acc.opening_balance, transactions=acc.transactions)
            account_checks.append((acc, verify(joined)))

    parties = enrich(accounts)
    tx = sorted((t for acc in accounts for t in acc.transactions), key=lambda t: t.date)

    printed = [p for ls in loaded for p in ls.statement.printed_returns]
    returns = build_returns(tx, printed)
    daily = total_daily_balances(accounts)
    cashflow = build_cashflow(accounts, returns.count_by_month(), daily)

    report = Report(
        statements=loaded, accounts=accounts, account_checks=account_checks, transactions=tx,
        parties=parties, returns=returns, cashflow=cashflow,
        month_parties=build_month_parties(tx), unknown=build_unknown(tx),
        loans=build_loans(tx, returns), recurring=build_recurring(tx), cheques=build_cheque_list(tx),
        modes_in=build_mode_split(tx, credit=True), modes_out=build_mode_split(tx, credit=False),
    )
    notes = [n for acc in accounts for n in acc.notes]
    report.flags = build_flags(tx, daily, returns, report.loans, notes, cashflow.total.avg_balance)
    report.suspicious = build_suspicion(loaded)
    report.flags[:0] = [Flag("high", suspicion_flag(s)) for s in report.suspicious]
    report.checks = build_checks(report)
    return report
