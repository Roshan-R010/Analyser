"""Work out which bank a statement is from.

Only the statement header (text above the transaction table) and the last page
are searched, because transactions mention other banks' names and IFSC codes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pdfplumber

from analyser.profiles import Profile, load_profiles

UNKNOWN = "unknown"

# Words that appear in a transaction table's heading row, grouped by meaning
_HEADING_GROUPS = [
    r"\bdate\b",
    r"balance\b",
    r"\b(debit|withdrawal)",
    r"\b(credit|deposit)",
    r"\b(particulars|narration|description|remarks)\b",
]
HEADER_WEIGHT = 2
FOOTER_WEIGHT = 1


@dataclass(frozen=True)
class Detection:
    bank: str  # profile id, or "unknown"
    scores: dict[str, int]


def header_text(page_text: str) -> str:
    """Text of the first page above the transaction table's heading row."""
    lines = page_text.splitlines()
    for i, line in enumerate(lines):
        # a heading row can wrap over up to three lines (only a line without digits can start one)
        wrapped = [line]
        # and that line must already look like part of a heading (2+ column words)
        starts = not re.search(r"\d", line) and sum(bool(re.search(g, line.lower())) for g in _HEADING_GROUPS) >= 2
        for nxt in lines[i + 1:i + 3] if starts else []:
            if re.search(r"\d", nxt):
                break
            wrapped.append(nxt)
        low = " ".join(wrapped).lower()
        if sum(bool(re.search(g, low)) for g in _HEADING_GROUPS) >= 3:
            return "\n".join(lines[:i])
    return page_text  # no table heading found: use the whole page


def detect_bank_from_text(first_page: str, last_page: str,
                          profiles: tuple[Profile, ...] | None = None) -> Detection:
    profiles = profiles if profiles is not None else load_profiles()
    head = header_text(first_page)
    scores = {}
    for p in profiles:
        score = sum(HEADER_WEIGHT for pat in p.detect_header if re.search(pat, head, re.I))
        score += sum(FOOTER_WEIGHT for pat in p.detect_footer if re.search(pat, last_page, re.I))
        scores[p.id] = score
    best = max(scores.values(), default=0)
    winners = [b for b, s in scores.items() if s == best]
    bank = winners[0] if best > 0 and len(winners) == 1 else UNKNOWN
    return Detection(bank=bank, scores=scores)


def detect_bank(pdf: pdfplumber.PDF) -> Detection:
    first = pdf.pages[0].extract_text() or ""
    last = pdf.pages[-1].extract_text() or ""
    return detect_bank_from_text(first, last)
