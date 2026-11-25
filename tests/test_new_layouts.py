"""The layouts and quirks found in the second batch of real statements, checked without private files."""
from datetime import date
from decimal import Decimal as D

from analyser.details import read_details
from analyser.detect import detect_bank_from_text
from analyser.model import Statement, Transaction
from analyser.profiles import load_profiles
from analyser.readers.generic import _is_newest_first
from analyser.readers.parse import find_dates
from analyser.unlock import read_password_file
from analyser.verify import verify


def _tx(debit="0", credit="0", balance=None):
    return Transaction(date=date(2026, 1, 1), description="x", debit=D(debit), credit=D(credit),
                       balance=D(balance) if balance is not None else None)


def _raw(bank):
    return next(p.raw for p in load_profiles() if p.id == bank)


def test_a_list_running_newest_first_is_recognised_from_its_balances():
    oldest_first = [_tx(credit="100", balance="150"), _tx(debit="30", balance="120"), _tx(debit="20", balance="100")]
    assert not _is_newest_first(oldest_first)
    assert _is_newest_first(oldest_first[::-1])


def test_an_overdrawn_balance_printed_without_its_minus_sign_still_adds_up():
    st = Statement(bank="indian_bank", opening_balance=D("205.46"),
                   transactions=[_tx(debit="1000", balance="794.54"),    # really -794.54
                                 _tx(credit="5000", balance="4205.46")])
    assert verify(st).ok
    assert st.transactions[0].balance == D("-794.54")


def test_a_wrong_balance_is_still_a_break():
    st = Statement(bank="x", opening_balance=D("100"), transactions=[_tx(debit="30", balance="50")])
    assert not verify(st).ok


def test_month_first_dates():
    assert find_dates("for the period May 1, 2026 - October 29, 2026") == [date(2026, 5, 1), date(2026, 10, 29)]


def test_dbs_is_recognised_by_its_account_summary():
    page = ("Account Details\nAccount Number : 0104360000001560 - INR Account Name : X -\n"
            "Product Type : CALSA CA Supreme\nOpening Balance : 1.00 01-May-2026 Earmark Amount : 0.00\n"
            "Ledger Balance : 2.00 31-Oct-2026 Overdraft Limit : 0.00\n"
            "Date Value Date Transaction Details Debit Credit Running Balance\n")
    assert detect_bank_from_text(page, "").bank == "dbs"


def test_icici_savings_download_is_recognised_and_its_holder_read():
    page = ("1\nStatement of Transactions in Saving Account no. 190901500546 in INR for the period May 1, 2026\n"
            "KUMARAVEL P Your Base Branch: ICICI BANK LIMITED,\n77,1ST MAIN ROAD\n"
            "Transaction Withdrawal Deposit Balance\n")
    assert detect_bank_from_text(page, "").bank == "icici"
    assert read_details(page, _raw("icici")).holder == "KUMARAVEL P"


def test_iob_newer_layout_holder_and_account_number():
    header = ("Customer ID : 1\n: 275001000009807\nAccount No : THIRUMALAIKUMAR T , SURVEY AREA NO.34/1\n"
              "IFS Code : IOBA0002750\n")
    d = read_details(header, _raw("iob"))
    assert (d.holder, d.account_no) == ("THIRUMALAIKUMAR T", "275001000009807")


def test_federal_holder_when_the_branch_name_follows_it():
    header = "Branch Name\nName : DHEERAN TRADERS : Mammudi ( Thalaivasal)\nIFSC : FDRL0002601\n"
    assert read_details(header, _raw("federal")).holder == "DHEERAN TRADERS"


def test_saved_password_matches_a_browser_style_file_name(tmp_path):
    f = tmp_path / "passwords.txt"
    f.write_text("# note\nAcct%20Statement_2042.pdf = secret\n", encoding="utf-8")
    book = read_password_file(f)
    assert book.get("Acct Statement_2042.pdf") == "secret"
    assert book.get("acct statement_2042.PDF") == "secret"
    assert book.get("other.pdf") is None


# ---------------------------------------------------------------- suspicious statements

def _loaded(bank, rows, opening="1000", pages=None):
    """A LoadedStatement from (debit, credit, balance) rows."""
    from analyser.engine import LoadedStatement
    st = Statement(bank=bank, opening_balance=D(opening), statement_no=1)
    for i, (d, c, b) in enumerate(rows):
        t = _tx(d, c, b)
        t.page_no = (pages or [1] * len(rows))[i]
        st.transactions.append(t)
    return LoadedStatement(statement=st, check=verify(st), file_name="x.pdf")


def test_a_known_bank_that_does_not_add_up_is_reportable_but_suspicious():
    ls = _loaded("hdfc", [("0", "500", "1500"), ("200", "0", "1400"), ("100", "0", "1200")])  # row 2 is off by 100
    assert not ls.supported and ls.reportable and ls.suspicious


def test_an_unknown_bank_or_a_mostly_broken_read_is_refused_not_suspicious():
    unknown = _loaded("unknown", [("0", "500", "1")])
    assert not unknown.reportable
    broken = _loaded("hdfc", [("0", "10", str(i * 7)) for i in range(40)])  # nearly every row breaks: a misread
    assert not broken.reportable


def test_suspicion_names_the_page_and_the_entry_and_the_gap():
    from analyser.sections.suspicion import build_suspicion, suspicion_flag
    ls = _loaded("hdfc", [("0", "500", "1500"), ("200", "0", "1400"), ("100", "0", "1300")], pages=[1, 3, 3])
    [s] = build_suspicion([ls])
    [f] = s.findings
    assert (f.page_no, f.previous, f.expected, f.printed, f.difference) == (3, D("1500"), D("1300"), D("1400"), D("100"))
    assert "page 3" in suspicion_flag(s) and "First entry on page 3" in f.hint
    assert s.level == "watch" and s.what_might_be_wrong


def test_a_suspicious_statement_gets_a_report_with_the_notice_on_the_first_page():
    from analyser.analysis import analyse
    from analyser.report.render import render_html
    ls = _loaded("hdfc", [("0", "500", "1500"), ("200", "0", "1400"), ("100", "0", "1300")])
    ls.statement.account_holder = "T"
    html = render_html(analyse([ls]))
    assert "Suspicious statement" in html and "Where it does not add up" in html and "SUSPICIOUS: statement 1" in html
