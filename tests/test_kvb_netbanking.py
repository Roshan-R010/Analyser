"""KVB's netbanking download ("Account Statement", made with Apache FOP), checked with made-up data.

The bank's name is only in the logo picture, and a long description runs on invisibly past its cell,
under the amount in the next column.
"""
from datetime import date
from decimal import Decimal as D

import pdfplumber

from analyser.details import read_details
from analyser.detect import detect_bank_from_text
from analyser.enrich.lenders import assign_lenders
from analyser.enrich.modes import assign_modes
from analyser.enrich.parties import assign_parties
from analyser.model import Transaction
from analyser.profiles import load_profiles
from analyser.readers.generic import OPENING_PRINTED, ReaderOptions
from analyser.readers.layout import page_geometry

HEADER = """Account Statement
as of 03-11-2026 10:00:00
Account Name SAMPLE TRADER
Account Holder(s) Name SAMPLE TRADERS / A PERSON / B PERSON
Account Number 1234135000000001
Branch SOMEWHERE
Customer Id 11111111
Account Currency INR
Opening Balance ( Balance B/F ) 1,23,456.78
Closing Balance 9,616.67
Searched by Specify Period
From Date 01-05-2026
To Date 03-11-2026
"""
PAGE = HEADER + "Transaction Date Value Date Branch Cheque No Description Debit Credit Balance\n"


def _kvb():
    return next(p.raw for p in load_profiles() if p.id == "kvb")


def test_recognised_without_the_bank_name_in_the_text():
    assert detect_bank_from_text(PAGE, "").bank == "kvb"


def test_holder_account_number_and_period():
    d = read_details(HEADER, _kvb())
    assert (d.holder, d.account_no) == ("SAMPLE TRADERS", "1234135000000001")
    assert (d.period_from, d.period_to) == (date(2026, 5, 1), date(2026, 11, 3))


def test_printed_opening_balance_with_a_note_in_brackets():
    m = OPENING_PRINTED.search(HEADER)
    assert m and D(m.group(1).replace(",", "")) == D("123456.78")


def _pdf(tmp_path, *texts):
    """A one-page PDF drawing each (x, y, text) in the order given."""
    stream = "".join(f"BT /F1 8 Tf {x} {y} Td ({t}) Tj ET\n" for x, y, t in texts)
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 200] /Contents 4 0 R "
               "/Resources << /Font << /F1 5 0 R >> >> >>",
               f"<< /Length {len(stream)} >>\nstream\n{stream}endstream",
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    body = "".join(f"{i} 0 obj\n{o}\nendobj\n" for i, o in enumerate(objects, 1))
    path = tmp_path / "overflow.pdf"
    path.write_bytes(f"%PDF-1.4\n{body}trailer\n<< /Root 1 0 R >>\n%%EOF".encode("latin-1"))
    return path


def test_description_running_under_the_amount_stays_separate_from_it(tmp_path):
    # The first string is wide enough to end past x=300, where the amount starts
    path = _pdf(tmp_path, (150, 100, "GSTNEW-00000000000000--00000000000000"), (150, 80, "H.O"),
                (300, 100, "7,000.00"))
    options = ReaderOptions.from_profile(_kvb())
    with pdfplumber.open(path) as pdf:
        assert pdf.pages[0].extract_words()[0]["x1"] > 300  # the two really do overlap
        words = [w.text for w in page_geometry(pdf.pages[0], options.y_tolerance, options.use_text_flow).words]
    assert "7,000.00" in words and "GSTNEW-00000000000000--00000000000000" in words


def test_a_biller_payment_is_with_the_payee_not_the_gateway():
    """KVB writes "GATEWAY-<reference>-<payee>--<account> H.O"; a lender paid this way must count."""
    t = Transaction(date=date(2026, 5, 5), debit=D("7000"), credit=D("0"),
                    description="IBIBO-00000000001-Bajaj Finance limited--1111102000000001 H.O")
    assign_modes([t])
    assign_parties([t], ["SAMPLE TRADERS"])
    assign_lenders([t])
    assert (t.mode, t.party_clean, t.lender) == ("Bill pay", "BAJAJ FINANCE LIMITED", "Bajaj Finance")


def test_a_gateway_paying_in_is_left_alone():
    t = Transaction(date=date(2026, 5, 5), debit=D("0"), credit=D("7000"),
                    description="RAZORPAY-SETTLEMENT-000000001")
    assign_modes([t])
    assign_parties([t], ["SAMPLE TRADERS"])
    assert (t.mode, t.party_clean) == ("Other", "RAZORPAY")
