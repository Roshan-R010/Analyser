"""The engine: statement PDFs in, checked statements and a report out.

    load_statement(path, password)  -> LoadedStatement (read + balance check)
    build_report(paths_and_passwords, out_pdf) -> report PDF (+ JSON) for one borrower

Front doors (command line now, website and WhatsApp later) only call these.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from analyser.detect import UNKNOWN, detect_bank, header_text
from analyser.details import read_details
from analyser.model import Statement
from analyser.profiles import load_profiles
from analyser.readers.generic import ReaderOptions, read_statement
from analyser.unlock import open_statement
from analyser.verify import VerifyResult, verify

FIRST_PAGE_DPI = 110


@dataclass
class LoadedStatement:
    statement: Statement
    check: VerifyResult
    file_name: str = ""
    first_page_png: bytes = field(default=b"", repr=False)  # picture of page 1 for the report

    @property
    def supported(self) -> bool:
        """True only when every balance adds up. Otherwise numbers must not be shown."""
        return self.check.ok


def _page_png(page) -> bytes:
    try:
        img = page.to_image(resolution=FIRST_PAGE_DPI).original
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        return b""  # the picture is nice to have; never fail the report over it


def load_statement(path: str | Path, password: str | None = None, statement_no: int = 1,
                   with_picture: bool = False) -> LoadedStatement:
    profiles = {p.id: p for p in load_profiles()}
    with open_statement(path, password) as pdf:
        bank = detect_bank(pdf).bank
        raw = profiles[bank].raw if bank != UNKNOWN else None
        st = read_statement(pdf, bank, ReaderOptions.from_profile(raw), statement_no=statement_no)
        details = read_details(header_text(pdf.pages[0].extract_text() or ""), raw)
        picture = _page_png(pdf.pages[0]) if with_picture else b""
    st.account_holder = details.holder
    st.account_no = details.account_no
    # The period printed on the statement wins over the first/last transaction dates
    st.period_from = details.period_from or st.period_from
    st.period_to = details.period_to or st.period_to
    return LoadedStatement(statement=st, check=verify(st), file_name=Path(path).name, first_page_png=picture)
