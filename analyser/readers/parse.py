"""Read amounts and dates written in any of the formats Indian banks use."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MONTHS["sept"] = 9

# Day first always (Indian statements). Year may be 2 or 4 digits.
_DATE_PATTERNS = [
    # 01-OCT-2026, 01 Oct 2026, 01-Oct-26, 01/Oct/2026
    re.compile(r"(?<!\d)(\d{1,2})[\s\-/.]*([A-Za-z]{3,4})[a-z]*[\s\-/.,']*(\d{4}|\d{2})(?!\d)"),
    # 01-10-2026, 01/10/26, 01.10.2026
    re.compile(r"(?<!\d)(\d{1,2})[\-/.](\d{1,2})[\-/.](\d{4}|\d{2})(?!\d)"),
    # 2026-10-01
    re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"),
]


def _year(y: str) -> int:
    n = int(y)
    return n + 2000 if n < 100 else n


def parse_date(text: str) -> date | None:
    """First date found in the text, or None."""
    if not text:
        return None
    for i, pat in enumerate(_DATE_PATTERNS):
        for m in pat.finditer(text):
            a, b, c = m.groups()
            try:
                if i == 0:
                    month = _MONTHS.get(b.lower()[:4]) or _MONTHS.get(b.lower()[:3])
                    if not month:
                        continue
                    return date(_year(c), month, int(a))
                if i == 1:
                    return date(_year(c), int(b), int(a))
                return date(int(a), int(b), int(c))
            except ValueError:
                continue
    return None


_AMOUNT = re.compile(r"^(\(?)(-?)([\d,]*\d(?:\.\d+)?)(\)?)\s*(cr|dr)?\.?$", re.I)


def parse_amount(text: str) -> Decimal | None:
    """Parse '1,00,000.50', '-', '0.00', '(500.00)', '1,234.00 Cr', '₹ 67058.89'.

    Returns None when the text is not an amount. A blank or '-' is zero.
    A trailing 'Dr' or brackets make it negative (used for overdrawn balances).
    """
    if text is None:
        return None
    t = text.replace("₹", "").replace("INR", "").replace("Rs.", "").replace("Rs", "")
    t = re.sub(r"\s+", " ", t).strip()
    if t in ("", "-", "--", "—"):
        return Decimal("0.00")
    t = t.replace(" ", "")
    t = re.sub(r"(?i)(cr|dr)\.?$", r" \1", t)
    # Some banks drop the leading zero: ".00", "-.50"
    t = re.sub(r"^(\(?-?)\.(\d)", r"\g<1>0.\2", t)
    m = _AMOUNT.match(t)
    if not m:
        return None
    open_b, minus, digits, close_b, side = m.groups()
    if digits.replace(",", "").count(".") > 1:
        return None
    try:
        value = Decimal(digits.replace(",", ""))
    except InvalidOperation:
        return None
    negative = bool(minus) or (open_b and close_b) or (side and side.lower() == "dr")
    return (-value if negative else value).quantize(Decimal("0.01"))


def amount_side(text: str) -> str:
    """'dr', 'cr' or '' from a Dr/Cr marker in the text."""
    m = re.search(r"\b(dr|cr|debit|credit|d|c)\b\.?", text or "", re.I)
    if not m:
        return ""
    return "dr" if m.group(1).lower().startswith("d") else "cr"


def find_dates(text: str) -> list[date]:
    """Every date in the text, in the order they appear."""
    found: list[tuple[int, date]] = []
    taken: list[tuple[int, int]] = []
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text or ""):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            d = parse_date(m.group(0))
            if d:
                found.append((m.start(), d))
                taken.append((m.start(), m.end()))
    return [d for _, d in sorted(found)]
