"""Whole-pipeline runs on made-up statements: tiny, lopsided and random ones must never crash.

A crash on an odd statement (one day, only credits, no debits, overdrawn, one huge party) is a worse
failure than a plain report, so these push the odd shapes through analyse() and the report HTML.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from analyser.analysis import analyse
from analyser.engine import LoadedStatement
from analyser.model import Statement, Transaction
from analyser.report.render import render_html, summary_json
from analyser.verify import verify

DESCRIPTIONS = [
    "UPI/CR/{n}/RAMESH V/SBIN/ramesh@ybl", "NEFT-HDFCN{n}-ABC TRADERS PVT LTD", "IMPS/P2A/{n}/KUMAR S/HDFC",
    "ATM WDL {n}", "CASH DEPOSIT BY SELF", "SMS CHRGS {n}", "INT.PD:01-01-26", "CHQ PAID {n}", "CLG/{n}/ACME CORP",
    "NACH-DR-BAJAJ FINANCE LTD-{n}", "ACH D- TATA CAPITAL-{n}", "INW CHQ RETURN {n} FUNDS INSUFFICIENT",
    "UPI/DR/{n}/MURUGAN T/IOBA/murugan@oksbi", "RTGS-ICICR{n}-GLOBAL STEELS", "", "   ", "BY TRANSFER-{n}",
]


def build(rows, opening="0", bank="axis", acc="9001", holder="TEST BORROWER", no=1):
    """rows: (date, signed amount, description). Balances are worked out, so the statement is consistent."""
    bal, txs = D(opening), []
    for d, amount, desc in rows:
        amount = D(amount)
        bal += amount
        txs.append(Transaction(date=d, description=desc, debit=-amount if amount < 0 else D("0.00"),
                               credit=amount if amount > 0 else D("0.00"), balance=bal, bank=bank, statement_no=no))
    st = Statement(bank=bank, account_no=acc, account_holder=holder, statement_no=no, opening_balance=D(opening),
                   transactions=txs, period_from=rows[0][0] if rows else None, period_to=rows[-1][0] if rows else None)
    return LoadedStatement(statement=st, check=verify(st), file_name=f"s{no}.pdf")


def run(*loaded):
    report = analyse(list(loaded))
    html = render_html(report)
    summary_json(report)
    return report, html


D1 = date(2026, 1, 5)


def test_one_transaction_one_day():
    r, html = run(build([(D1, "500", "CASH DEPOSIT BY SELF")]))
    assert r.cashflow.total.credit == D("500") and len(r.cashflow.months) == 1 and "Cashflow Summary" in html


def test_only_debits_and_only_credits():
    run(build([(D1, "-100", "ATM WDL 1"), (D1 + timedelta(days=1), "-50", "SMS CHRGS 2")], opening="1000"))
    run(build([(D1, "100", "UPI/CR/1/A B/SBIN/x@ybl"), (D1 + timedelta(days=40), "50", "NEFT-HDFCN1-C D")]))


def test_overdrawn_account_and_zero_balance():
    r, _ = run(build([(D1, "-500", "CHQ PAID 1"), (D1 + timedelta(days=2), "500", "CASH DEPOSIT")], opening="100"))
    assert any(f.level == "high" for f in r.flags)  # balance below zero is flagged


def test_empty_and_blank_descriptions_do_not_break_anything():
    r, _ = run(build([(D1, "100", ""), (D1, "-20", "   "), (D1 + timedelta(days=1), "5", "x")]))
    assert all(t.party_key for t in r.transactions) and all(t.mode for t in r.transactions)


def test_two_accounts_of_one_borrower():
    a = build([(D1, "100", "CASH DEPOSIT")], acc="1", no=1)
    b = build([(D1 + timedelta(days=3), "-30", "ATM WDL 7")], opening="500", acc="2", bank="hdfc", no=2)
    r, _ = run(a, b)
    assert len(r.accounts) == 2 and r.cashflow.total.credit == D("100") and r.cashflow.total.debit == D("30")


def test_same_account_in_two_consecutive_statements():
    a = build([(D1, "100", "CASH DEPOSIT"), (D1 + timedelta(days=10), "-40", "ATM WDL 1")], opening="1000", no=1)
    last = a.statement.transactions[-1].balance
    b = build([(D1 + timedelta(days=45), "60", "CASH DEPOSIT")], opening=str(last), no=2)
    r, _ = run(a, b)
    assert len(r.accounts) == 1 and r.account_checks and r.account_checks[0][1].ok
    assert any("Gap" in n for n in r.accounts[0].notes)


def test_a_loan_paid_monthly_a_missed_month_and_a_bounce():
    rows = [(date(2026, m, 5), "-25000", "NACH-DR-BAJAJ FINANCE LTD-123") for m in (1, 2, 4, 5)]
    rows.insert(0, (date(2026, 1, 1), "200000", "CASH DEPOSIT BY SELF"))
    rows.append((date(2026, 5, 20), "-5000", "INW CHQ RETURN 4421 FUNDS INSUFFICIENT"))
    r, html = run(build(rows))
    [loan] = [ln for ln in r.loans if ln.payments]
    assert loan.emi == D("25000") and [m.month for m in loan.months_missed] == [3]
    assert "Loan transactions" in html


@pytest.mark.parametrize("seed", range(12))
def test_random_statements_never_crash_and_stay_consistent(seed):
    rnd = random.Random(seed)
    rows, d, n = [], date(2025, rnd.randint(1, 6), rnd.randint(1, 28)), 0
    for _ in range(rnd.choice([1, 2, 5, 40, 300])):
        d += timedelta(days=rnd.choice([0, 0, 1, 2, 9, 31]))
        n += 1
        amount = D(rnd.choice([5, 100, 999, 25000, 150000, 1234567])) * rnd.choice([-1, 1]) + D(rnd.choice(["0", "0.5", "0.99"]))
        rows.append((d, amount, rnd.choice(DESCRIPTIONS).format(n=rnd.randint(10**5, 10**9))))
    r, html = run(build(rows, opening=str(rnd.choice([0, 500, 10**6]))))
    cf = r.cashflow
    # every rupee in the statement lands in exactly one month, one party and one payment mode
    assert sum((m.credit for m in cf.months), D(0)) == cf.total.credit == sum((t.credit for t in r.transactions), D(0))
    assert sum((m.debit for m in cf.months), D(0)) == cf.total.debit
    for mp in r.month_parties:
        assert sum((c.amount for c in mp.credits), D(0)) == mp.credit_total
        assert sum((c.amount for c in mp.debits), D(0)) == mp.debit_total
    assert r.all_checks_ok, [c for c in r.checks if not c.ok]
    assert "<table" in html


def test_flag_and_summary_quote_the_same_average_balance():
    from analyser.fmt import inr
    rows = []
    for i in range(5):  # money in, and almost all of it out the same day, every few weeks
        rows += [(D1 + timedelta(days=i * 20), "100000", "CASH DEPOSIT"), (D1 + timedelta(days=i * 20), "-99990", "ATM WDL 1")]
    r, _ = run(build(rows, opening="0"))
    [flag] = [f.text for f in r.flags if "little is kept" in f.text]  # a pass-through account is flagged...
    assert inr(r.cashflow.total.avg_balance) in flag  # ...with the same average balance the summary shows


def test_a_short_statement_shows_everything_a_long_one_would():
    """No time limits: one week of data still fills the recurring page and every cashflow row."""
    rows = [(D1, "300000", "CASH DEPOSIT BY SELF")]
    rows += [(D1 + timedelta(days=i), "-6000", "UPI/DR/1/RAMESH TEXTILES/IOBA/ramesh@oksbi") for i in range(1, 6)]
    r, html = run(build(rows))
    assert [x.party for x in r.recurring] == ["RAMESH TEXTILES"]
    assert all(r.cashflow.last[n] is not None for n in (3, 6, 9, 12)) and "not enough months" not in html
    assert "the statement has only 1 month" in html


def test_a_party_paid_three_times_in_one_month_of_a_longer_statement_is_listed_too():
    rows = [(D1, "300000", "CASH DEPOSIT BY SELF")]
    rows += [(D1 + timedelta(days=i), "-6000", "UPI/DR/1/RAMESH TEXTILES/IOBA/ramesh@oksbi") for i in range(1, 6)]
    rows += [(D1 + timedelta(days=70), "-100", "ATM WDL 1")]
    r, _ = run(build(rows))
    assert [x.party for x in r.recurring] == ["RAMESH TEXTILES"]


def test_cheque_page_includes_cheques_that_print_no_number():
    rows = [(D1, "100000", "CASH DEPOSIT BY SELF"),
            (D1 + timedelta(days=1), "30000", "CLG/ACME TRADERS/KVB"),  # a deposited cheque, no number printed
            (D1 + timedelta(days=2), "-5000", "CHQ NO 004455 RAMESH"),
            (D1 + timedelta(days=3), "-200", "ATM WDL 77"), (D1 + timedelta(days=4), "-300", "NEFT-HDFCN1-ABC")]
    r, html = run(build(rows))
    assert [(t.cheque_no, t.date.day) for t in r.cheques] == [("4455", 7), ("", 6)]  # numbered first, then the rest
    assert "Cheque-wise transactions" in html and "Cheques deposited" in html and "Cheques issued" in html


def test_an_atm_or_upi_reference_is_not_a_cheque_number():
    from analyser.enrich.cheques import assign_cheques
    from analyser.enrich.modes import assign_modes
    atm = Transaction(date=D1, description="ATM WDL 55", debit=D("500"), ref_no="0000000000001933")
    chq = Transaction(date=D1, description="CHQ PAID-SELF", debit=D("500"), ref_no="0000000000000117")
    zero = Transaction(date=D1, description="CHQ PAID-SELF", debit=D("500"), ref_no="000000000000000")
    for t in (atm, chq, zero):
        assign_modes([t])
        assign_cheques([t])
    assert (atm.cheque_no, chq.cheque_no, zero.cheque_no) == ("", "117", "")


def _loan_entries(name, amounts, ltype="Private finance", start=date(2026, 1, 5), mode="Cheque"):
    out = []
    for i, a in enumerate(amounts):
        out.append(Transaction(date=start + timedelta(days=14 * i), description=f"CLG/{name}/KCU", debit=D(a),
                               balance=D("1000"), mode=mode, lender=name, lender_type=ltype, party_clean=name))
    return out


def test_one_lender_spelled_two_ways_is_one_loan_with_a_note():
    from analyser.sections.loans import build_loans, loan_blocks
    from analyser.sections.returns import ReturnsSection
    tx = _loan_entries("ARASAN FINANCE", ["50000"] * 6) + _loan_entries("ABASAN FINANCE", ["50000"], start=date(2026, 4, 1))
    [loan] = build_loans(tx, ReturnsSection(bounces=[], transfer_returns=[]))
    assert loan.lender == "ARASAN FINANCE" and loan.payments == 7 and loan.paid_total == D("350000")
    assert any("Abasan Finance" in n for n in loan.notes)
    assert "also spelled" in loan_blocks([loan])[0].subline


def test_similar_names_with_different_amounts_or_types_stay_apart():
    from analyser.sections.loans import build_loans
    from analyser.sections.returns import ReturnsSection
    none = ReturnsSection(bounces=[], transfer_returns=[])
    # same-looking name but a payment amount the other never gets: not merged
    tx = _loan_entries("ARASAN FINANCE", ["50000"] * 4) + _loan_entries("ABASAN FINANCE", ["12345"], start=date(2026, 4, 1))
    assert len(build_loans(tx, none)) == 2
    # a different kind of lender: not merged
    tx = _loan_entries("ARASAN FINANCE", ["50000"] * 4) + _loan_entries("ABASAN FINANCE", ["50000"], ltype="Chit fund")
    assert len(build_loans(tx, none)) == 2
    # genuinely different names
    tx = _loan_entries("ARASAN FINANCE", ["50000"] * 4) + _loan_entries("FINANCEMOHAN", ["50000"])
    assert len(build_loans(tx, none)) == 2


def test_a_lender_name_seen_once_is_only_a_possible_lender():
    from analyser.sections.flags import build_flags
    from analyser.sections.loans import POSSIBLE, build_loans
    from analyser.sections.returns import ReturnsSection
    none = ReturnsSection(bounces=[], transfer_returns=[])
    loans = build_loans(_loan_entries("ARASAN FINANCE", ["50000"] * 4) + _loan_entries("FINANCEMOHAN", ["50000"], mode="IMPS"), none)
    by_name = {ln.lender: ln for ln in loans}
    assert by_name["FINANCEMOHAN"].type == POSSIBLE and by_name["ARASAN FINANCE"].type == "Private finance"
    flags = build_flags([], {}, none, loans, [])
    assert any("Paying 1 lender" in f.text for f in flags)  # the possible lender is not counted
