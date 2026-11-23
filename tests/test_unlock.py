import pytest

from analyser.unlock import NotAPdf, PasswordRequired, StatementError, WrongPassword, open_statement
from conftest import statement


def test_open_plain_pdf():
    with open_statement(statement("indianoverseas.pdf")) as pdf:
        assert len(pdf.pages) > 0


def test_locked_pdf_without_password():
    with pytest.raises(PasswordRequired):
        open_statement(statement("KVB.pdf"))


def test_locked_pdf_with_wrong_password():
    with pytest.raises(WrongPassword):
        open_statement(statement("KVB.pdf"), "definitely-wrong")


def test_locked_pdf_with_right_password(passwords):
    if "KVB.pdf" not in passwords:
        pytest.skip("no password for KVB.pdf")
    with open_statement(statement("KVB.pdf"), passwords["KVB.pdf"]) as pdf:
        assert pdf.pages[0].extract_text()


def test_missing_file(tmp_path):
    with pytest.raises(StatementError, match="not found"):
        open_statement(tmp_path / "nope.pdf")


def test_not_a_pdf(tmp_path):
    fake = tmp_path / "fake.pdf"
    fake.write_text("hello")
    with pytest.raises(NotAPdf):
        open_statement(fake)


def test_error_message_never_contains_password(tmp_path):
    try:
        open_statement(statement("KVB.pdf"), "secret-pw-123")
    except WrongPassword as exc:
        assert "secret-pw-123" not in str(exc)
