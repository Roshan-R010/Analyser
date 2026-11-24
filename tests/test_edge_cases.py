"""Edge cases and odd inputs: formats, parsing, combining, empty and tiny statements.

These use no real statements, so they run anywhere. Each one pins a behaviour that is easy to break.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from analyser.combine import combine
from analyser.details import read_details
from analyser.enrich.modes import classify
from analyser.enrich.parties import extract_name, name_key
from analyser.fmt import inr, inr2, inr_paise
from analyser.model import Statement, Transaction
from analyser.readers.parse import amount_side, find_dates, parse_amount, parse_date
from analyser.unlock import NotAPdf, StatementError, open_statement
from analyser.verify import verify


def tx(d, debit="0", credit="0", balance=None, desc="X", **kw):
    return Transaction(date=d, description=desc, debit=D(debit), credit=D(credit),
                       balance=None if balance is None else D(balance), **kw)


# ---------------------------------------------------------------- amounts

@pytest.mark.parametrize("text,expected", [
    ("1,23,456.78", "123456.78"), ("1,234", "1234.00"), ("0.00", "0.00"), ("-", "0.00"), ("", "0.00"),
    ("  ", "0.00"), ("--", "0.00"), ("(500.00)", "-500.00"), ("500.00 Dr", "-500.00"), ("500.00Dr", "-500.00"),
    ("500 CR", "500.00"), ("500.00 Cr.", "500.00"), ("₹ 67,058.89", "67058.89"), ("Rs. 1,000.50", "1000.50"),
    ("INR 2,500.00", "2500.00"), (".50", "0.50"), ("-.50", "-0.50"), ("1,000.5", "1000.50"), ("-250", "-250.00"),
    ("1000", "1000.00"), ("0", "0.00"),
])
def test_parse_amount_formats(text, expected):
    assert parse_amount(text) == D(expected)


@pytest.mark.parametrize("text", ["abc", "1.2.3", "12-34", "Dr", "1,2,3x", "NA", "01/02/2026"])
def test_parse_amount_rejects_text(text):
    assert parse_amount(text) is None


def test_parse_amount_none_and_unicode_minus():
    assert parse_amount(None) is None
    assert parse_amount("−5,000.00") == D("-5000.00")  # a typographic minus sign


@pytest.mark.parametrize("text,side", [("Dr", "dr"), ("CR", "cr"), ("500.00 DR", "dr"), ("Credit", "cr"),
                                       ("Debit", "dr"), ("", ""), ("1,000.00", "")])
def test_amount_side(text, side):
    assert amount_side(text) == side


# ---------------------------------------------------------------- dates

@pytest.mark.parametrize("text,expected", [
    ("01-10-2026", date(2026, 10, 1)), ("1/10/26", date(2026, 10, 1)), ("01.10.2026", date(2026, 10, 1)),
    ("01-OCT-2026", date(2026, 10, 1)), ("01 Oct 2026", date(2026, 10, 1)), ("01-Oct-26", date(2026, 10, 1)),
    ("1/Sept/2026", date(2026, 9, 1)), ("2026-10-01", date(2026, 10, 1)), ("29/02/2028", date(2028, 2, 29)),
    ("posted 05/11/2026 12:30", date(2026, 11, 5)), ("01 June 2026", date(2026, 6, 1)),
])
def test_parse_date_formats(text, expected):
    assert parse_date(text) == expected


@pytest.mark.parametrize("text", ["", "no date", "31-02-2026", "2026-13-01", "00-01-2026", "32/01/2026", "12345"])
def test_parse_date_rejects(text):
    assert parse_date(text) is None


def test_find_dates_keeps_order_and_does_not_double_count():
    assert find_dates("From 01/05/2026 To 31/10/2026") == [date(2026, 5, 1), date(2026, 10, 31)]
    assert find_dates("period 2026-05-01 to 2026-10-31") == [date(2026, 5, 1), date(2026, 10, 31)]
    assert find_dates("") == [] and find_dates(None) == []


# ---------------------------------------------------------------- money formatting

@pytest.mark.parametrize("x,whole,paise", [
    (D("0"), "0", "0"), (D("999"), "999", "999"), (D("1000"), "1,000", "1,000"), (D("123456"), "1,23,456", "1,23,456"),
    (D("12345678"), "1,23,45,678", "1,23,45,678"), (D("-1234567"), "-12,34,567", "-12,34,567"),
    (D("1234.50"), "1,235", "1,234.50"), (D("2.5"), "3", "2.50"), (D("0.5"), "1", "0.50"),
    (D("-0.4"), "0", "-0.40"), (D("30851.88"), "30,852", "30,851.88"), (D("42432.00"), "42,432", "42,432"),
    (D("0.004"), "0", "0"),
])
def test_rupee_formats(x, whole, paise):
    assert inr(x) == whole  # halves round up, and a tiny negative is never "-0"
    assert inr2(x) == paise


def test_rupee_formats_for_missing_and_ints():
    assert inr(None) == inr2(None) == "–" and inr_paise(None) == "-"
    assert inr(1234567) == "12,34,567" and inr2(5) == "5"
    assert inr_paise(D("1234567.5")) == "12,34,567.50" and inr_paise(D("-5")) == "-5.00"


# ---------------------------------------------------------------- balance check

def test_balance_check_empty_and_unknown_opening():
    assert not verify(Statement(bank="x")).ok  # nothing read
    assert "Opening balance unknown" in verify(Statement(bank="x", transactions=[tx(date(2026, 1, 1), "5", balance="5")])).problems


def test_balance_check_one_bad_row_is_one_break():
    d = date(2026, 1, 1)
    rows = [tx(d, "100", balance="900"), tx(d, "50", balance="850"), tx(d, "0", "20", balance="800"),
            tx(d, "10", balance="790")]
    res = verify(Statement(bank="x", opening_balance=D("1000"), transactions=rows))
    assert [b.index for b in res.breaks] == [2] and not res.ok  # carries on from the printed balance


def test_balance_check_totals_and_reversals():
    d = date(2026, 1, 1)
    rows = [tx(d, "100", balance="900"), tx(d, "0", "100", balance="1000")]
    ok = Statement(bank="x", opening_balance=D("1000"), transactions=rows,
                   printed_total_debit=D("100"), printed_total_credit=D("100"), printed_closing=D("1000"))
    assert verify(ok).ok
    wrong = Statement(bank="x", opening_balance=D("1000"), transactions=rows, printed_total_debit=D("101"))
    assert not verify(wrong).ok
    # a bank that nets a reversal off its own column prints totals lower by the reversal on both sides
    netted = Statement(bank="x", opening_balance=D("1000"), transactions=rows, reversal_total=D("100"),
                       printed_total_debit=D("0"), printed_total_credit=D("0"))
    assert verify(netted).ok


def test_balance_check_missing_balance_is_a_break():
    d = date(2026, 1, 1)
    res = verify(Statement(bank="x", opening_balance=D("10"), transactions=[tx(d, "0", "5")]))
    assert not res.ok and res.breaks[0].printed is None


# ---------------------------------------------------------------- combining statements

def _st(no, rows, opening, acc="111", bank="axis", start=None, end=None):
    return Statement(bank=bank, account_no=acc, statement_no=no, opening_balance=D(opening), transactions=rows,
                     period_from=start or rows[0].date, period_to=end or rows[-1].date)


def test_combine_overlap_gap_and_order():
    a = [tx(date(2026, 1, 5), "0", "100", "1100"), tx(date(2026, 1, 20), "50", "0", "1050")]
    b = [tx(date(2026, 1, 20), "50", "0", "1050"), tx(date(2026, 2, 3), "0", "10", "1060")]
    [acc] = combine([_st(2, b, "1100", start=date(2026, 1, 15)), _st(1, a, "1000", start=date(2026, 1, 1))])
    assert [t.date.day for t in acc.transactions] == [5, 20, 3]  # sorted by statement, the repeat counted once
    assert verify(Statement(bank="axis", opening_balance=acc.opening_balance, transactions=acc.transactions)).ok
    assert any("overlaps" in n for n in acc.notes)

    c = [tx(date(2026, 3, 10), "0", "5", "1065")]
    [acc] = combine([_st(1, a, "1000"), _st(2, c, "1060")])
    assert any(n.startswith("Gap") for n in acc.notes)


def test_combine_keeps_different_accounts_and_unnumbered_statements_apart():
    r = [tx(date(2026, 1, 5), "0", "100", "1100")]
    assert len(combine([_st(1, list(r), "1000", acc="111"), _st(2, list(r), "1000", acc="222")])) == 2
    assert len(combine([_st(1, list(r), "1000", acc=""), _st(2, list(r), "1000", acc="")])) == 2
    assert len(combine([_st(1, list(r), "1000", bank="axis"), _st(2, list(r), "1000", bank="hdfc")])) == 2


def test_combine_two_identical_entries_in_one_day_are_both_kept():
    same = [tx(date(2026, 1, 5), "10", "0", "990"), tx(date(2026, 1, 5), "10", "0", "980")]
    [acc] = combine([_st(1, same, "1000")])
    assert len(acc.transactions) == 2


# ---------------------------------------------------------------- opening a file

def test_open_statement_errors(tmp_path):
    with pytest.raises(StatementError):
        open_statement(tmp_path / "missing.pdf")
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"this is not a pdf")
    with pytest.raises(NotAPdf):
        open_statement(junk)
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    with pytest.raises(StatementError):
        open_statement(empty)


# ---------------------------------------------------------------- statement details

def test_details_generic_and_profile_patterns():
    head = "Account Name: RAMESH TRADERS   Branch: X\nAccount No: 123456789012\nPeriod 01/04/2026 to 30/06/2026"
    d = read_details(head)
    assert d.holder == "RAMESH TRADERS" and d.account_no == "123456789012"
    assert (d.period_from, d.period_to) == (date(2026, 4, 1), date(2026, 6, 30))
    custom = read_details("Hello\nHOLDER ONE PVT LTD  more", {"details": {"holder": r"^(?P<h>HOLDER ONE PVT LTD)"}})
    assert custom.holder == "HOLDER ONE PVT LTD"
    assert read_details("").holder == "" and read_details("").period_from is None
    assert read_details("Name : M/S. SIRAJ MILK AGENCY").holder == "SIRAJ MILK AGENCY"  # honorific dropped


def test_details_reversed_period_is_ignored():
    assert read_details("period 30/06/2026 to 01/04/2026").period_from is None


# ---------------------------------------------------------------- modes and names on odd text

@pytest.mark.parametrize("desc", ["", "   ", "\n", None])
def test_mode_and_name_on_empty_description(desc):
    t = Transaction(date=date(2026, 1, 1), description=desc or "", debit=D("1"))
    assert classify(t) == "Other"
    assert extract_name(desc or "") == ""


@pytest.mark.parametrize("desc,mode", [
    ("NEFT/AXISCN1234/ABC TRADERS", "NEFT"), ("RTGS-HDFCR52026-XYZ", "RTGS"), ("UPI/CR/1234/NAME/SBIN", "UPI"),
    ("ATM WDL/12345", "Cash"), ("CHQ PAID-SELF", "Cash"), ("SMS CHRGS 2026", "Charges"), ("INT.PD:01-01-26", "Interest"),
    ("NACH-DR-BAJAJ FINANCE", "ECS/NACH"), ("POS 1234 AMAZON", "Card"), ("BIL/BPAY/123", "Bill pay"),
    ("INW CLG CHQ RETURN", "Return"), ("PAYMENT TO RAMESH", "Other"),
])
def test_mode_rules(desc, mode):
    assert classify(Transaction(date=date(2026, 1, 1), description=desc, debit=D("1"))) == mode


def test_name_key_ignores_spacing_punctuation_and_company_suffix():
    assert name_key("BRIGHT AUTOMATIONS") == name_key("BRIGHTAUTOMATIONS") == name_key("Bright Automations Pvt. Ltd.")
    assert name_key("") == "" and name_key("PVT LTD") != "x"
