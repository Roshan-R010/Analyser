"""The generic reader: turns any text-based statement PDF into standard transactions.

How it works, page by page:
1. Find the transaction table's heading row and work out the columns.
   Pages without a heading reuse the columns from the previous page.
2. Split the page into rows: by horizontal ruled lines when the page has them,
   otherwise each row starts at a date in the date column.
3. Read each row's cells into a Transaction.

Bank profiles only adjust this (e.g. extra heading names, how wrapped text joins).
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from decimal import Decimal

from analyser.model import ZERO, Statement, Transaction
from analyser.readers.layout import Line, PageGeometry, Table, Word, find_table, page_geometry
from analyser.readers.parse import amount_side, parse_amount, parse_date

OPENING_PATTERNS = re.compile(r"\b(b/?f|brought forward|opening balance|balance forward)\b", re.I)
# In date-anchored mode, a line like this ends the table on that page
STOP_PATTERNS = re.compile(
    r"(generated on|page \d+ (of|/) \d+|computer generated|system.generated|"
    r"^total\b|closing balance|denotes|statement summary|end of statement)", re.I)
TOTALS_PATTERNS = [
    (re.compile(r"total\s*debits?\s*:?\s*(?:rs\.?|inr|₹)?\s*([\d,]+\.\d{2})", re.I), "debit"),
    (re.compile(r"total\s*credits?\s*:?\s*(?:rs\.?|inr|₹)?\s*([\d,]+\.\d{2})", re.I), "credit"),
]


@dataclass
class ReaderOptions:
    # How wrapped description lines are joined:
    #   " "    always with a space (default)
    #   "auto" no space when a line runs to the column's right edge (word was cut),
    #          a space otherwise. For banks with narrow, hard-wrapped columns.
    description_join: str = " "
    extra_columns: list[tuple[str, str]] = field(default_factory=list)  # (heading regex, field)

    @classmethod
    def from_profile(cls, raw: dict | None) -> "ReaderOptions":
        cfg = (raw or {}).get("reader") or {}
        extra = [(pat, fld) for pat, fld in (cfg.get("columns") or {}).items()]
        return cls(description_join=cfg.get("description_join", " "), extra_columns=extra)


@dataclass
class CellLine:
    text: str
    x0: float
    x1: float


@dataclass
class RawRow:
    cells: dict[str, list[CellLine]]  # field -> lines of text in that cell
    bounds: dict[str, tuple[float, float]]  # field -> column's left and right edge
    page_no: int
    top: float


def read_statement(pdf, bank: str = "unknown", options: ReaderOptions | None = None,
                   statement_no: int = 0) -> Statement:
    options = options or ReaderOptions()
    st = Statement(bank=bank, page_count=len(pdf.pages), statement_no=statement_no)
    table: Table | None = None
    rows: list[RawRow] = []
    for page_no, page in enumerate(pdf.pages, start=1):
        geo = page_geometry(page)
        found = find_table(geo, options.extra_columns)
        if found:
            table = found
            start_y = found.header_bottom
        elif table is None:
            continue  # no table seen yet (cover page, summary page)
        else:
            start_y = 0.0
        rows.extend(_page_rows(geo, table, start_y, page_no))

    if table is None:
        st.warnings.append("No transaction table found (format not supported yet)")
        return st

    for row in rows:
        _add_row(st, row, options)
    _read_printed_totals(pdf, st)
    if st.opening_balance is None and st.transactions and st.transactions[0].balance is not None:
        first = st.transactions[0]
        st.opening_balance = first.balance - first.amount
    if st.transactions:
        st.period_from = st.period_from or st.transactions[0].date
        st.period_to = st.period_to or st.transactions[-1].date
    return st


# ---------------------------------------------------------------- rows

def _is_anchor(line_words: list[Word], table: Table) -> bool:
    """Does this line start a transaction (a date in the date column)?"""
    date_col = table.by_field()["date"]
    text = " ".join(w.text for w in line_words if date_col.x0 <= w.xc < date_col.x1)
    return parse_date(text) is not None or bool(re.match(r"\d{1,2}[-/ ][A-Za-z]{3}[-/ ]?$", text))


def _page_rows(geo: PageGeometry, table: Table, start_y: float, page_no: int) -> list[RawRow]:
    lines = [Line([w for w in ln.words]) for ln in geo.lines if ln.top > start_y]
    if not lines:
        return []
    anchors = [ln for ln in lines if _is_anchor(ln.words, table)]
    if not anchors:
        return []

    groups = _groups_by_rules(lines, anchors, geo.h_rules)
    if groups is None:
        groups = _groups_by_anchor(lines, anchors)

    bounds = {c.field: (c.x0, c.x1) for c in table.columns}
    rows = []
    for grp in groups:
        cells: dict[str, list[CellLine]] = {}
        for ln in grp:
            per_field: dict[str, list[Word]] = {}
            for w in ln.words:
                col = table.column_of(w)
                if col is None or col.field == "other":
                    continue
                per_field.setdefault(col.field, []).append(w)
            for fld, ws in per_field.items():
                cells.setdefault(fld, []).append(
                    CellLine(" ".join(w.text for w in ws), ws[0].x0, ws[-1].x1))
        rows.append(RawRow(cells=cells, bounds=bounds, page_no=page_no, top=grp[0].top))
    return rows


def _groups_by_rules(lines: list[Line], anchors: list[Line], rules: list[float]) -> list[list[Line]] | None:
    """Rows = spaces between horizontal ruled lines. None if the rules don't fit."""
    if len(rules) < 2:
        return None
    band_of = {}
    for ln in lines:
        y = (ln.top + ln.bottom) / 2
        i = bisect.bisect(rules, y)
        band_of[id(ln)] = i if 0 < i < len(rules) else None
    anchor_bands = [band_of[id(a)] for a in anchors]
    if None in anchor_bands or len(set(anchor_bands)) != len(anchor_bands):
        return None  # an anchor outside the rules, or two transactions in one band
    groups: dict[int, list[Line]] = {b: [] for b in anchor_bands}
    for ln in lines:
        b = band_of[id(ln)]
        if b in groups:
            groups[b].append(ln)
    return [groups[b] for b in sorted(groups)]


def _groups_by_anchor(lines: list[Line], anchors: list[Line]) -> list[list[Line]]:
    """Rows start at each dated line and run until the next one."""
    anchor_ids = {id(a) for a in anchors}
    groups: list[list[Line]] = []
    for ln in lines:
        if id(ln) in anchor_ids:
            groups.append([ln])
        elif groups:
            if STOP_PATTERNS.search(ln.text):
                break
            groups[-1].append(ln)
    return groups


# ---------------------------------------------------------------- transactions

WRAP_SLACK = 8.0  # a line ending this close to the column's text edge was cut mid-word


def _cell(row: RawRow, fld: str, join: str = " ") -> str:
    lines = row.cells.get(fld, [])
    if join != "auto" or len(lines) < 2:
        return (" " if join == "auto" else join).join(ln.text for ln in lines).strip()
    # Text sits inside the column with the same padding on both sides
    left, right = row.bounds[fld]
    pad = max(0.0, min(ln.x0 for ln in lines) - left)
    text_edge = right - pad
    out = lines[0].text
    for prev, ln in zip(lines, lines[1:]):
        cut = prev.x1 >= text_edge - WRAP_SLACK or prev.text.endswith(("-", "/"))
        out += ("" if cut else " ") + ln.text
    return out.strip()


def _date(row: RawRow, fld: str):
    lines = [ln.text for ln in row.cells.get(fld, [])]
    return parse_date(" ".join(lines)) or parse_date("".join(lines))


def _add_row(st: Statement, row: RawRow, opt: ReaderOptions) -> None:
    where = f"page {row.page_no}"
    txn_date = _date(row, "date")
    if txn_date is None:
        st.warnings.append(f"{where}: row without a readable date skipped: {_cell(row, 'description')[:60]!r}")
        return

    balance = parse_amount(_cell(row, "balance")) if "balance" in row.cells else None
    description = _cell(row, "description", opt.description_join)

    if "amount" in row.cells:
        amount = parse_amount(_cell(row, "amount"))
        side = amount_side(_cell(row, "drcr")) or amount_side(_cell(row, "amount"))
        if amount is None or not side:
            st.warnings.append(f"{where}: unreadable amount on {txn_date}: {_cell(row, 'amount')!r}")
            return
        debit, credit = (abs(amount), ZERO) if side == "dr" else (ZERO, abs(amount))
    else:
        debit = parse_amount(_cell(row, "debit"))
        credit = parse_amount(_cell(row, "credit"))
        if debit is None or credit is None:
            st.warnings.append(
                f"{where}: unreadable amount on {txn_date}: "
                f"debit {_cell(row, 'debit')!r} credit {_cell(row, 'credit')!r}")
            return
        debit, credit = abs(debit), abs(credit)

    if debit == ZERO and credit == ZERO:
        if not st.transactions and balance is not None and OPENING_PATTERNS.search(description):
            st.opening_balance = balance
            return
        st.warnings.append(f"{where}: row with no amount on {txn_date}: {description[:60]!r}")

    st.transactions.append(Transaction(
        date=txn_date,
        value_date=_date(row, "value_date"),
        description=description,
        ref_no=_cell(row, "ref_no", ""),
        cheque_no=_cell(row, "cheque_no", ""),
        code=_cell(row, "code", ""),
        debit=debit,
        credit=credit,
        balance=balance,
        bank=st.bank,
        statement_no=st.statement_no,
        page_no=row.page_no,
    ))


def _read_printed_totals(pdf, st: Statement) -> None:
    """Totals the bank prints itself (usually on the last page)."""
    text = pdf.pages[-1].extract_text() or ""
    for pattern, side in TOTALS_PATTERNS:
        m = pattern.search(text)
        if m:
            value = Decimal(m.group(1).replace(",", ""))
            if side == "debit":
                st.printed_total_debit = value
            else:
                st.printed_total_credit = value
