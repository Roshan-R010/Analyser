import pytest

from analyser.detect import UNKNOWN, detect_bank, detect_bank_from_text, header_text
from analyser.unlock import open_statement
from conftest import statement


@pytest.mark.parametrize("name,bank", [
    ("icic.pdf", "icici"),
    ("indianoverseas.pdf", "iob"),
    ("KVB.pdf", "kvb"),
])
def test_detects_real_statements(name, bank, passwords):
    with open_statement(statement(name), passwords.get(name)) as pdf:
        assert detect_bank(pdf).bank == bank


def test_header_stops_at_table_heading():
    page = "MY BANK\nIFSC IOBA0001234\nDATE NARRATION DEBIT CREDIT BALANCE\nUPI/ICIC0000001/x"
    assert "ICIC0000001" not in header_text(page)
    assert "IOBA0001234" in header_text(page)


def test_other_banks_in_transactions_do_not_confuse_it():
    # A KVB statement whose transactions mention ICICI and IOB codes
    page = ("ACCOUNT STATEMENT\nAcc. Type : KVB ADVANTAGE CA\n"
            "Txn Date Particulars Debit Credit Balance\n"
            "RTGS ICIC0000001 IOBA0000002 ICICI")
    assert detect_bank_from_text(page, "").bank == "kvb"


def test_unknown_bank():
    page = "SOME OTHER BANK\nDate Narration Debit Credit Balance\n"
    assert detect_bank_from_text(page, "").bank == UNKNOWN
