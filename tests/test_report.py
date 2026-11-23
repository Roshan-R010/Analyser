"""End-to-end on a small made-up statement: analyse -> HTML -> PDF (no real data)."""
from datetime import date
from decimal import Decimal as D

import pdfplumber
import pytest

from analyser.analysis import analyse
from analyser.engine import LoadedStatement
from analyser.model import Statement, Transaction
from analyser.report.render import inr2, render_html, summary_json, write_report
from analyser.verify import verify


def _statement() -> LoadedStatement:
    rows = [  # (date, description, debit, credit)
        (date(2026, 1, 3), "NEFT-HDFCH00711112222-GOOD CUSTOMER LTD-0001", 0, 200000),
        (date(2026, 1, 5), "BIL/ONL/001100003333/Lendingkar", 42432, 0),
        (date(2026, 1, 9), "CAM/01111ABC/CASHDEP-Self/09-01-26/1234", 0, 50000),
        (date(2026, 1, 12), "CLG/RAVI KUMAR/KCU", 60000, 0),
        (date(2026, 1, 12), "RETURNED:000123:FUNDS INSUFFICIENT", 0, 60000),
        (date(2026, 1, 13), "IW RTN CHQ CHGS", 590, 0),
        (date(2026, 1, 20), "MMT/IMPS/600011112222/Ramesh/INDB0000123", 10000, 0),
        (date(2026, 2, 4), "BIL/ONL/001100004444/Lendingkar", 42432, 0),
        (date(2026, 2, 10), "MMT/IMPS/600011113333/Ramesh/INDB0000123", 10000, 0),
        (date(2026, 2, 15), "INF/INFT/045000001111/SELF", 20000, 0),
        (date(2026, 3, 2), "NEFT-HDFCH00711113333-GOOD CUSTOMER LTD-0001", 0, 150000),
        (date(2026, 3, 9), "MMT/IMPS/600011114444/Ramesh/INDB0000123", 10000, 0),
        (date(2026, 3, 30), "BIL/ONL/001100005555/Lendingkar", 42432, 0),
    ]
    bal = D("1000.00")
    tx = []
    for d, desc, dr, cr in rows:
        bal = bal + D(cr) - D(dr)
        tx.append(Transaction(date=d, description=desc, debit=D(dr).quantize(D("0.01")),
                              credit=D(cr).quantize(D("0.01")), balance=bal, bank="icici",
                              cheque_no="123" if "CLG/RAVI" in desc else ""))
    st = Statement(bank="icici", account_holder="TEST TRADERS", account_no="000111222333",
                   period_from=date(2026, 1, 1), period_to=date(2026, 3, 31),
                   opening_balance=D("1000.00"), transactions=tx, statement_no=1)
    return LoadedStatement(statement=st, check=verify(st), file_name="test.pdf")


@pytest.fixture(scope="module")
def report():
    return analyse([_statement()])


def test_analysis_on_made_up_statement(report):
    assert report.all_checks_ok, [c for c in report.checks if not c.ok]
    assert [b.kind for b in report.returns.bounces] == ["Funds"]
    assert report.returns.bounces[0].charge_total == D("590.00")
    lk = next(ln for ln in report.loans if ln.lender == "Lendingkart")
    assert lk.payments == 3 and lk.emi == D("42432.00") and not lk.months_missed
    assert [m.returns for m in report.cashflow.months] == [1, 0, 0]
    assert any(r.party == "RAMESH" for r in report.recurring)
    assert sum(1 for t in report.transactions if t.party_clean == "Self") == 1
    assert sum(1 for t in report.transactions if t.party_clean == "Cash") == 1


def test_html_has_every_section(report):
    html = render_html(report)
    for heading in ("Flags", "Cashflow Summary", "Chq/ECS Return Txns", "Recurring Debits", "Loan Txns",
                    "CounterParty Totals", "Unknown Txns", "Chq No Wise Txns", "Visual Analytics"):
        assert heading in html, heading
    assert html.count("<svg") == 4
    assert "TEST TRADERS" in html and "XXXX2333" in html and "000111222333" not in html


def test_pdf_is_printed(report, tmp_path):
    paths = write_report(report, tmp_path / "r.pdf")
    with pdfplumber.open(paths["pdf"]) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    assert "Cashflow Summary" in text and "Lendingkart" in text
    assert summary_json(report)["all_checks_ok"] is True


def test_money_format():
    assert inr2(D("3085188") / 100) == "30,851.88"
    assert inr2(D("42432.00")) == "42,432"
    assert inr2(D("-1234567.5")) == "-12,34,567.50"
