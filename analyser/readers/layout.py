"""Page geometry: words, text lines, ruled lines, and the transaction table's columns.

Nothing here knows about any particular bank. Columns are found from the heading
row's words; a bank profile can add heading names the generic list doesn't know.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

LINE_TOLERANCE = 2.0  # words whose tops differ by less than this are on one line
COLUMN_GAP = 6.0  # a horizontal gap wider than this separates heading columns
HEADER_SECOND_LINE = 14.0  # max distance to a wrapped second heading line

# Heading text -> field. Checked in order; the first match wins.
FIELD_RULES: list[tuple[str, str]] = [
    (r"^(s ?no|sl ?no|sr ?no|serial.*)$", "other"),
    (r"^(cod|code|tran ?code|txn ?code|trn ?code)$", "code"),
    (r"value ?(date|dt)", "value_date"),
    (r"^(dr ?cr|cr ?dr|type|dr cr)$", "drcr"),
    (r"(chq|cheque|instrument).*(ref)|(ref).*(chq|cheque)", "ref_no"),
    (r"chq|cheque|instrument", "cheque_no"),
    (r"\bref|reference|\b(transaction|tran|txn) ?id\b|utr", "ref_no"),
    (r"balance", "balance"),
    (r"withdrawal|debit|\bdr\b|paid out", "debit"),
    (r"deposit|credit|\bcr\b|paid in", "credit"),
    (r"amount|amt", "amount"),
    (r"date|\bdt\b", "date"),
    (r"particular|narration|description|remark|detail", "description"),
]

# Used to recognise the heading row itself: at least 3 of these groups present
HEADING_GROUPS = [
    r"\bdate\b",
    r"balance\b",
    r"\b(debit|withdrawal)",
    r"\b(credit|deposit)",
    r"\b(particulars|narration|description|remarks|details)\b",
]


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def yc(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass
class Line:
    words: list[Word]

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class Column:
    name: str  # heading text, e.g. "Withdrawal (Dr)"
    field: str  # standard field, e.g. "debit"
    x0: float  # words whose centre falls in [x0, x1) belong to this column
    x1: float


@dataclass
class Table:
    columns: list[Column]
    header_bottom: float  # y below which the transactions start on this page

    def by_field(self) -> dict[str, Column]:
        return {c.field: c for c in self.columns if c.field != "other"}

    def column_of(self, word: Word) -> Column | None:
        for c in self.columns:
            if c.x0 <= word.xc < c.x1:
                return c
        return None


@dataclass
class PageGeometry:
    words: list[Word]
    lines: list[Line]
    h_rules: list[float]  # y positions of horizontal ruled lines
    v_rules: list[tuple[float, float, float]]  # (x, top, bottom) of vertical ruled lines
    width: float
    height: float = 0.0
    extra: dict = field(default_factory=dict)


def page_geometry(page, y_tolerance: float = 3) -> PageGeometry:
    """y_tolerance: how far apart (points) letters may sit and still be one word's line. Statements
    that set 6-point text on 6-point lines need a smaller value, or neighbouring lines get mixed."""
    raw = page.extract_words(keep_blank_chars=False, use_text_flow=False, y_tolerance=y_tolerance)
    words = [Word(w["text"], w["x0"], w["x1"], w["top"], w["bottom"]) for w in raw]
    h, v = [], []
    for e in page.edges:
        if e["orientation"] == "h" and (e["x1"] - e["x0"]) > 20:
            h.append(round(e["top"], 1))
        elif e["orientation"] == "v" and (e["bottom"] - e["top"]) > 5:
            v.append((round(e["x0"], 1), e["top"], e["bottom"]))
    return PageGeometry(words=words, lines=group_lines(words), h_rules=_dedupe(h),
                        v_rules=v, width=page.width, height=page.height)


def group_lines(words: list[Word]) -> list[Line]:
    lines: list[Line] = []
    for w in sorted(words, key=lambda w: (w.top, w.x0)):
        if lines and abs(lines[-1].words[0].top - w.top) < LINE_TOLERANCE:
            lines[-1].words.append(w)
        else:
            lines.append(Line([w]))
    for ln in lines:
        ln.words.sort(key=lambda w: w.x0)
    return lines


def _dedupe(values: list[float], tol: float = 1.0) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def normalise_heading(text: str) -> str:
    t = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return re.sub(r"\s+", " ", t).strip()


def field_for(heading: str, extra_rules: list[tuple[str, str]] | None = None) -> str:
    name = normalise_heading(heading)
    for pattern, fld in (extra_rules or []) + FIELD_RULES:
        if re.search(pattern, name):
            return fld
    return "other"


def is_heading_line(text: str) -> bool:
    low = text.lower()
    return sum(bool(re.search(g, low)) for g in HEADING_GROUPS) >= 3


def find_table(geo: PageGeometry, extra_rules: list[tuple[str, str]] | None = None) -> Table | None:
    """Find the transaction table's heading row on this page and build its columns."""
    for i, line in enumerate(geo.lines):
        # The heading may wrap over up to three lines ("Withdra" / "wal" / "(Dr)"), so the words that
        # name the columns can be spread across them
        wrapped = [line]
        starts = not re.search(r"\d", line.text) and sum(bool(re.search(g, line.text.lower())) for g in HEADING_GROUPS) >= 2
        for nxt in geo.lines[i + 1:i + 3] if starts else []:
            if nxt.top - wrapped[-1].top > HEADER_SECOND_LINE or re.search(r"\d", nxt.text):
                break
            wrapped.append(nxt)
        if not is_heading_line(" ".join(ln.text for ln in wrapped)):
            continue
        heading_lines = [line]
        for nxt in geo.lines[i + 1:i + 3]:
            gap = nxt.top - heading_lines[-1].top
            if gap > HEADER_SECOND_LINE or re.search(r"\d", nxt.text):
                break
            heading_lines.append(nxt)
        table = _build_columns(geo, heading_lines, extra_rules)
        if table:
            return table
    return None


def _build_columns(geo: PageGeometry, heading_lines: list[Line],
                   extra_rules: list[tuple[str, str]] | None) -> Table | None:
    first = heading_lines[0]
    top, bottom = first.top, heading_lines[-1].bottom

    # Column bands: from vertical ruled lines crossing the heading, if there are enough
    xs = sorted({x for x, t, b in geo.v_rules if t <= first.bottom and b >= first.top})
    xs = _dedupe(xs, tol=2.0)
    groups: list[list[Word]] = []
    bands: list[tuple[float, float]] = []
    if len(xs) >= 4:
        for a, b in zip(xs, xs[1:]):
            ws = [w for w in first.words if a <= w.xc < b]
            if ws:
                groups.append(ws)
                bands.append((a, b))
    else:
        for w in first.words:
            if groups and w.x0 - groups[-1][-1].x1 < COLUMN_GAP:
                groups[-1].append(w)
            else:
                groups.append([w])
        # Boundaries halfway between neighbouring headings
        for k, g in enumerate(groups):
            left = 0.0 if k == 0 else (groups[k - 1][-1].x1 + g[0].x0) / 2
            right = geo.width if k == len(groups) - 1 else (g[-1].x1 + groups[k + 1][0].x0) / 2
            bands.append((left, right))

    names = [" ".join(w.text for w in g) for g in groups]
    # Wrapped heading words (e.g. "Withdrawal" / "(Dr)") join the column above them
    for ln in heading_lines[1:]:
        for w in ln.words:
            for k, (a, b) in enumerate(bands):
                if a <= w.xc < b:
                    names[k] += " " + w.text
                    break

    columns, seen = [], set()
    for name, (a, b) in zip(names, bands):
        fld = field_for(name, extra_rules)
        if fld in seen:
            fld = "other"  # keep the first column for each field
        seen.add(fld)
        columns.append(Column(name=name, field=fld, x0=a, x1=b))

    fields = {c.field for c in columns}
    has_amounts = {"debit", "credit"} <= fields or "amount" in fields
    if "date" not in fields or "balance" not in fields or not has_amounts:
        return None
    return Table(columns=columns, header_bottom=bottom)
