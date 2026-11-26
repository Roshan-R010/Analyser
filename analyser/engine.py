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
from analyser.readers.parallel import page_geometries
from analyser.unlock import open_statement
from analyser.verify import VerifyResult, verify

FIRST_PAGE_DPI = 110
MAX_SUSPECT_BREAKS = 5  # a known layout with more broken rows than this (and 20% of rows) is a misread


@dataclass
class LoadedStatement:
    statement: Statement
    check: VerifyResult
    file_name: str = ""
    first_page_png: bytes = field(default=b"", repr=False)  # picture of page 1 for the report

    @property
    def supported(self) -> bool:
        """True when every balance adds up."""
        return self.check.ok

    @property
    def reportable(self) -> bool:
        """A report can be made from it: it adds up, or it is a layout we know whose numbers don't
        (then it is reported as suspicious). An unknown bank, a layout that reads no rows or breaks
        on most of them is a reading failure, not a finding: those are refused."""
        c, st = self.check, self.statement
        if c.ok:
            return True
        if st.bank == UNKNOWN or not st.transactions or st.opening_balance is None:
            return False
        return len(c.breaks) <= max(MAX_SUSPECT_BREAKS, c.rows_checked // 5)

    @property
    def suspicious(self) -> bool:
        return self.reportable and not self.check.ok


def covering_period(printed_from, printed_to, transactions):
    """The period of several statements merged into one PDF: page 1 prints only the first one's, so it is
    widened to take in every entry."""
    dates = [t.date for t in transactions]
    start = min([d for d in (printed_from, min(dates, default=None)) if d], default=None)
    end = max([d for d in (printed_to, max(dates, default=None)) if d], default=None)
    return start, end


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
        options = ReaderOptions.from_profile(raw)
        geometries = page_geometries(path, password, len(pdf.pages),
                                     options.y_tolerance, options.use_text_flow)
        st = read_statement(pdf, bank, options, statement_no=statement_no, geometries=geometries)
        details = read_details(header_text(pdf.pages[0].extract_text() or ""), raw)
        picture = _page_png(pdf.pages[0]) if with_picture else b""
    st.account_holder = details.holder
    st.account_no = details.account_no
    # The period printed on the statement wins over the first/last transaction dates
    st.period_from = details.period_from or st.period_from
    st.period_to = details.period_to or st.period_to
    if st.merged_sections > 1:
        st.period_from, st.period_to = covering_period(st.period_from, st.period_to, st.transactions)
    return LoadedStatement(statement=st, check=verify(st), file_name=Path(path).name, first_page_png=picture)
