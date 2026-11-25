"""Open a statement PDF, unlocking it with a password if needed.

The password is used only to open the file. It is never stored or logged.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfplumber.utils.exceptions import PdfminerException


class StatementError(Exception):
    """A statement could not be opened. The message is safe to show the user."""


class PasswordRequired(StatementError):
    pass


class WrongPassword(StatementError):
    pass


class NotAPdf(StatementError):
    pass


class PasswordBook(dict):
    """Passwords by file name. Look-ups ignore case and browser-style escapes (`%20` for a space)."""

    def get(self, name, default=None):
        return super().get(unquote(name).lower(), default)


def read_password_file(path: str | Path) -> PasswordBook:
    """Read `filename.pdf = password` lines (blank lines and # comments are skipped)."""
    book = PasswordBook()
    path = Path(path)
    if not path.is_file():
        return book
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, pw = line.split("=", 1)
            book[unquote(name.strip()).lower()] = pw.strip()
    return book


def _is_password_error(exc: PdfminerException) -> bool:
    return any(isinstance(a, PDFPasswordIncorrect) for a in exc.args)


def open_statement(path: str | Path, password: str | None = None) -> pdfplumber.PDF:
    """Open the PDF and return it. The caller must close it (use `with`)."""
    path = Path(path)
    if not path.is_file():
        raise StatementError(f"File not found: {path.name}")
    try:
        pdf = pdfplumber.open(path, password=password or "")
        # pdfplumber opens lazily; touching the pages forces decryption now
        len(pdf.pages)
    except PdfminerException as exc:
        if _is_password_error(exc):
            if password:
                raise WrongPassword(f"Wrong password for {path.name}") from None
            raise PasswordRequired(f"{path.name} is password protected") from None
        raise NotAPdf(f"{path.name} could not be read as a PDF") from None
    except Exception:
        raise NotAPdf(f"{path.name} could not be read as a PDF") from None
    if not pdf.pages:
        pdf.close()
        raise NotAPdf(f"{path.name} has no pages")
    return pdf
