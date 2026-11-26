"""IDFC quirks, checked with made-up data: a long description printing on past its cell into the amount
columns, and several statements of one account merged into one PDF."""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

from analyser.engine import covering_period
from analyser.model import Transaction
from analyser.profiles import load_profiles
from analyser.readers.generic import ReaderOptions, read_statement
from analyser.readers.layout import PageGeometry, Word, group_lines
from analyser.verify import verify

EDGES = [32, 111, 190, 296, 348, 427, 506, 585]  # the table's vertical rules


def _options():
    return ReaderOptions.from_profile(next(p.raw for p in load_profiles() if p.id == "idfc"))


def _page(*lines):
    """A page of (top, [(x0, x1, text), ...]) lines under the table's heading."""
    heading = [(40, 60, "Date"), (119, 135, "Value"), (137, 160, "Date"), (198, 250, "Particulars"),
               (302, 335, "Cheque"), (370, 395, "Debit"), (450, 480, "Credit"), (530, 565, "Balance")]
    words = [Word(text, x0, x1, top, top + 8) for top, ws in [(100, heading), *lines] for x0, x1, text in ws]
    return PageGeometry(words=words, lines=group_lines(words), h_rules=[],
                        v_rules=[(x, 90.0, 700.0) for x in EDGES], width=612)


def _read(*pages):
    pdf = SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda g=g: "\n".join(ln.text for ln in g.lines))
                                 for g in pages])
    return read_statement(pdf, "idfc", _options(), geometries=list(pages))


DATES = [(40, 82, "01-May-2026"), (119, 162, "01-May-2026")]


def test_description_printing_into_the_amount_columns_is_put_back():
    page = _page((200, [*DATES, (198, 250, "NEFT/RAZORPAY"), (464, 505, "2,000.00"), (538, 584, "3,000.00")]),
                 (254, [(198, 295, "DOCOMO,BANGALORE,KA"), (300.5, 350.5, "RNATAKA,IND"), (353.4, 361, "IA")]))
    st = _read(page)
    assert [(t.debit, t.credit, t.cheque_no) for t in st.transactions] == [(D("0.00"), D("2000.00"), "")]
    assert st.transactions[0].description.split()[-3:] == ["DOCOMO,BANGALORE,KA", "RNATAKA,IND", "IA"]
    assert not st.warnings


def test_a_stray_digit_does_not_change_the_amount_beside_it():
    page = _page((200, [*DATES, (198, 270, "POS-VISA/GOOGLE"), (393, 425, "12,345.67"), (538, 584, "3,000.00")]),
                 (211, [(198, 293, "00000000/0000000000/0000"), (300.5, 348, "000000/00:00"), (355.3, 360, "8")]))
    t = _read(page).transactions[0]
    assert (t.debit, t.cheque_no) == (D("12345.67"), "")


def test_a_cheque_number_beside_a_short_description_stays():
    page = _page((200, [*DATES, (198, 270, "CHQ Paid"), (300.5, 330, "000004"), (393, 425, "500.00"),
                        (538, 584, "3,000.00")]))
    assert _read(page).transactions[0].cheque_no == "000004"


def test_spilled_text_on_a_line_of_its_own_is_not_an_amount():
    page = _page((200, [*DATES, (198, 250, "NEFT/x"), (464, 505, "2,000.00"), (538, 584, "3,000.00")]),
                 (212, [(198, 217, "TATA"), (351.8, 359.2, "IA")]))
    st = _read(page)
    assert len(st.transactions) == 1 and st.transactions[0].debit == D("0.00") and not st.warnings


def _section(opening, debit, credit, closing, row):
    summary = [(40, 90, "Opening Balance"), (95, 150, "Total Debit"), (155, 210, "Total Credit"),
               (215, 280, "Closing Balance")]
    figures = [(40, 90, opening), (95, 150, debit), (155, 210, credit), (215, 280, closing)]
    page = _page((200, [*DATES, (198, 250, "UPI/x"), *row]))
    words = [Word(text, x0, x1, top, top + 8) for top, ws in ((40, summary), (55, figures)) for x0, x1, text in ws]
    page.words = words + page.words
    page.lines = group_lines(page.words)
    return page


def test_totals_of_merged_statements_are_added_up():
    st = _read(_section("1,000.00", "100.00", "0.00", "900.00", [(393, 425, "100.00"), (538, 584, "900.00")]),
               _section("900.00", "0.00", "50.00", "950.00", [(464, 505, "50.00"), (538, 584, "950.00")]))
    assert (st.printed_total_debit, st.printed_total_credit) == (D("100.00"), D("50.00"))
    assert verify(st).ok, verify(st).problems


def test_a_summary_repeated_on_every_page_counts_once():
    st = _read(_section("1,000.00", "200.00", "0.00", "800.00", [(393, 425, "100.00"), (538, 584, "900.00")]),
               _section("1,000.00", "200.00", "0.00", "800.00", [(393, 425, "100.00"), (538, 584, "800.00")]))
    assert st.printed_total_debit is None or st.printed_total_debit == D("200.00")
    assert st.merged_sections == 1


def test_merged_statements_are_noticed():
    st = _read(_section("1,000.00", "100.00", "0.00", "900.00", [(393, 425, "100.00"), (538, 584, "900.00")]),
               _section("900.00", "0.00", "50.00", "950.00", [(464, 505, "50.00"), (538, 584, "950.00")]))
    assert st.merged_sections == 2


def test_period_covers_entries_after_the_first_printed_one():
    tx = [Transaction(date=date(2026, 4, 2), description="a"), Transaction(date=date(2026, 11, 16), description="b")]
    assert covering_period(date(2026, 4, 1), date(2026, 4, 30), tx) == (date(2026, 4, 1), date(2026, 11, 16))
    assert covering_period(date(2026, 4, 1), date(2026, 12, 1), tx) == (date(2026, 4, 1), date(2026, 12, 1))
    assert covering_period(None, None, tx) == (date(2026, 4, 2), date(2026, 11, 16))
