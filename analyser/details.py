"""Statement details from the top of page 1: account holder, account number, period.

Generic patterns first; a bank profile can give its own `details.holder` pattern
(a regex whose named groups are joined with spaces) when the layout is unusual.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from analyser.readers.parse import find_dates

ACCOUNT_NO = re.compile(
    r"(?:account\s*(?:number|no)|acc\.?\s*no|a/c\.?\s*no)\.?\s*[:\-]?\s*(\d[\d ]{7,22}\d)", re.I)

# The name ends at a wide gap, the end of the line, or the next label on the same line
_NEXT_LABEL = (
    r"(?=\s{2,}"
    r"|\s+(?:account|acct|a/c|acc|branch|customer|cust|ifsc|address|type|date|period"
    r"|currency|micr|mobile|phone|email|ckyc|scheme)\b[^:\n]{0,20}:"
    r"|$)"
)
HOLDER = [
    re.compile(r"(?:account|customer|a/c)\s*(?:holder\s*)?name\s*[:\-]\s*(?P<h>.+?)" + _NEXT_LABEL,
               re.I | re.M),
    re.compile(r"^\s*name\s*[:\-]\s*(?P<h>.+?)" + _NEXT_LABEL, re.I | re.M),
]
PERIOD_LINE = re.compile(r"(period|from|statement of|between)", re.I)
# The two ends of the period on lines of their own
FROM_TO = [re.compile(rf"^\s*{end}\s*date\s*[:\-]?\s*(\S+)\s*$", re.I | re.M) for end in ("from", "to")]


@dataclass
class Details:
    holder: str = ""
    account_no: str = ""
    period_from: date | None = None
    period_to: date | None = None


def _clean(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip(" :,-")
    return re.sub(r"^(M/S\.?|MS\.?|MR\.?|MRS\.?)\s+", "", name, flags=re.I)


def _as_list(value) -> list[str]:
    """A profile gives one pattern or a list of them (a bank may print its header in two layouts)."""
    return [value] if isinstance(value, str) else list(value or [])


def read_details(header: str, profile_raw: dict | None = None) -> Details:
    d = Details()

    cfg = (profile_raw or {}).get("details") or {}
    own = (re.search(p, header, re.M) for p in _as_list(cfg.get("account_no")))
    m = next(filter(None, own), None) or ACCOUNT_NO.search(header)
    if m:
        d.account_no = m.group(1).replace(" ", "")

    patterns = [re.compile(p, re.M) for p in _as_list(cfg.get("holder"))] + HOLDER
    for pat in patterns:
        m = pat.search(header)
        if m:
            parts = [v for v in m.groupdict().values() if v] or [m.group(0)]
            d.holder = _clean(" ".join(parts))
            if d.holder:
                break

    for line in header.splitlines():
        if PERIOD_LINE.search(line):
            dates = find_dates(line)
            if len(dates) >= 2 and dates[0] <= dates[1]:
                d.period_from, d.period_to = dates[0], dates[1]
                break
    if d.period_from is None:
        ends = [find_dates(m.group(1)) for m in (p.search(header) for p in FROM_TO) if m]
        if len(ends) == 2 and all(ends) and ends[0][0] <= ends[1][0]:
            d.period_from, d.period_to = ends[0][0], ends[1][0]
    return d
