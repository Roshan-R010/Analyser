"""Reader building blocks, tested without any real statement."""
import pytest

from analyser.readers.generic import CellLine, RawRow, _cell, _groups_by_anchor, _groups_by_rules
from analyser.readers.layout import Line, Word, field_for, is_heading_line


@pytest.mark.parametrize("heading,field", [
    ("Txn Date", "date"), ("Transaction date", "date"), ("DATE", "date"), ("Tran Dt", "date"),
    ("Value Date", "value_date"), ("Value Dt", "value_date"),
    ("Particulars", "description"), ("NARRATION", "description"), ("Description", "description"),
    ("Transaction Details", "description"), ("Remarks", "description"),
    ("Withdrawal (Dr)", "debit"), ("DEBIT", "debit"), ("Withdrawal Amt.", "debit"), ("Withdrawals", "debit"),
    ("Deposit (Cr)", "credit"), ("CREDIT", "credit"), ("Deposit Amt.", "credit"), ("Deposits", "credit"),
    ("Available Balance", "balance"), ("Closing Balance", "balance"), ("BALANCE", "balance"),
    ("Ref. No.", "ref_no"), ("Chq./Ref.No.", "ref_no"), ("Transaction ID", "ref_no"),
    ("CHQ NO", "cheque_no"), ("Cheque No", "cheque_no"), ("Instrument No", "cheque_no"),
    ("Amount", "amount"), ("Dr/Cr", "drcr"), ("Type", "drcr"),
    ("S.no", "other"), ("COD", "code"), ("Init. Br", "other"),
])
def test_heading_names(heading, field):
    assert field_for(heading) == field


def test_profile_can_add_heading_names():
    assert field_for("Txn Particulars Info", [("txn particulars info", "description")]) == "description"
    assert field_for("Mode") == "other"
    assert field_for("Mode", [("^mode$", "ref_no")]) == "ref_no"


def test_heading_line():
    assert is_heading_line("Txn Date Value Date Particulars Ref. No. Debit Credit Balance")
    assert is_heading_line("DATE CHQ NO NARRATION COD DEBIT CREDIT BALANCE")
    assert not is_heading_line("Statement for the period from 01/07/2026 to 11/11/2026")


def _line(top, text):
    return Line([Word(text, 0, 10, top, top + 8)])


def test_rows_by_anchor_stop_at_footer():
    lines = [_line(10, "01-JUL-2026 A"), _line(20, "wrapped"), _line(30, "02-JUL-2026 B"),
             _line(40, "Generated on : 21 Nov"), _line(50, "junk")]
    groups = _groups_by_anchor(lines, [lines[0], lines[2]])
    assert [[l.text for l in g] for g in groups] == [["01-JUL-2026 A", "wrapped"], ["02-JUL-2026 B"]]


def test_rows_by_rules_ref_above_date():
    # KVB style: reference number above the date, time below, all inside one ruled band
    lines = [_line(128, "ref1"), _line(133, "02-OCT-2026"), _line(142, "03:58"),
             _line(158, "ref2"), _line(163, "02-OCT-2026"), _line(172, "07:29")]
    groups = _groups_by_rules(lines, [lines[1], lines[4]], [126.0, 156.0, 186.0])
    assert [[l.text for l in g] for g in groups] == [["ref1", "02-OCT-2026", "03:58"], ["ref2", "02-OCT-2026", "07:29"]]


def test_rules_rejected_when_two_transactions_share_a_band():
    lines = [_line(10, "01-JUL-2026"), _line(20, "02-JUL-2026")]
    assert _groups_by_rules(lines, lines, [0.0, 100.0]) is None


def test_auto_join_cut_words():
    row = RawRow(cells={"description": [
        # Real lines from an ICICI statement
        CellLine("MMT/IMPS/6", 296.3, 343.4),  # reaches the edge: word was cut
        CellLine("001122334", 296.3, 339.5),  # also cut
        CellLine("45/Raghave", 296.3, 344.2),  # cut
        CellLine("ndra", 296.3, 312.0),  # short line: ended at a real space
        CellLine("TRADERS", 296.3, 330.0),
    ]}, bounds={"description": (286.3, 353.5)}, page_no=1, top=0)
    assert _cell(row, "description", "auto") == "MMT/IMPS/600112233445/Raghavendra TRADERS"
    assert _cell(row, "description", " ") == "MMT/IMPS/6 001122334 45/Raghave ndra TRADERS"


def test_profile_printed_totals_and_balances():
    import re as _re
    from analyser.readers.generic import CLOSING_PRINTED, OPENING_PRINTED, ReaderOptions
    opts = ReaderOptions.from_profile({"totals": {"pattern": r"TRANSACTION\s+TOTAL\s+(?P<debit>[\d,]+\.\d{2})\s+(?P<credit>[\d,]+\.\d{2})"}})
    m = _re.search(opts.totals_pattern, "TRANSACTION TOTAL 1279.42 1216.00", _re.I)
    assert (m.group("debit"), m.group("credit")) == ("1279.42", "1216.00")
    assert OPENING_PRINTED.search("OPENING BALANCE 128541.23").group(1) == "128541.23"
    assert CLOSING_PRINTED.search("Closing Balance : 65,191.81 Dr").groups() == ("65,191.81", "Dr")
    assert CLOSING_PRINTED.search("The closing balance as shown includes funds under clearing") is None
