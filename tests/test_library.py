"""Every statement in the private library must still read exactly as expected.

Expected totals live in tests/expected/<name>.yaml (made by tools/make_expected.py).
This is what stops a fix for one bank from breaking another.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from conftest import EXPECTED, ROOT, STATEMENTS, library_pdfs, load

sys.path.insert(0, str(ROOT / "tools"))
from make_expected import summarise  # noqa: E402


CASES = sorted(EXPECTED.glob("*.yaml")) if EXPECTED.is_dir() else []


def _pdf_for(expected: Path) -> Path | None:
    return next((p for p in library_pdfs() if p.stem == expected.stem), None)


@pytest.mark.parametrize("expected", CASES, ids=[c.stem for c in CASES])
def test_statement_reads_as_expected(expected, passwords):
    pdf = _pdf_for(expected)
    if pdf is None:
        pytest.skip(f"{expected.stem}.pdf not present")
    loaded = load(pdf.name)
    breaks = [(b.page_no, b.date, b.description) for b in loaded.check.breaks[:5]]
    assert loaded.check.ok, f"balance check failed: {breaks} {loaded.check.problems}"
    assert summarise(loaded) == yaml.safe_load(expected.read_text(encoding="utf-8"))


@pytest.mark.parametrize("pdf", library_pdfs(rejected=True), ids=lambda p: p.stem)
def test_rejected_statement_stays_rejected(pdf, passwords):
    """A statement whose own balances don't add up (bank error or an edited file) is never reported."""
    loaded = load(pdf.name)
    assert not loaded.check.ok and not loaded.supported


def test_every_statement_has_expected_totals():
    """A statement dropped into the library without expected totals is a reminder, not silence."""
    if not STATEMENTS.is_dir():
        pytest.skip("no statement library")
    # An exact copy of another statement (same bytes) is the same test twice: it needs no totals of its own
    import hashlib
    groups: dict[str, list[Path]] = {}
    for p in library_pdfs():
        groups.setdefault(hashlib.sha256(p.read_bytes()).hexdigest(), []).append(p)
    missing = [copies[0].name for copies in groups.values()
               if not any((EXPECTED / (p.stem + ".yaml")).is_file() for p in copies)]
    names = [p.name.lower() for p in library_pdfs()]
    assert len(names) == len(set(names)), "two statements share a file name (passwords and expected files go by name)"
    assert not missing, f"run tools/make_expected.py for: {missing}"


def test_parallel_page_reading_matches_single_process():
    """Long statements are read on several cores; the result must be exactly the single-core one."""
    from analyser.engine import load_statement
    from analyser.readers import parallel
    from conftest import find_statement, load_passwords
    pdf = find_statement("ICICI2.pdf")
    if pdf is None:
        pytest.skip("ICICI2.pdf not present")
    fast = load_statement(pdf, load_passwords().get(pdf.name)).statement
    old = parallel.MIN_PAGES
    parallel.MIN_PAGES = 10**6  # force the single-process path
    try:
        slow = load_statement(pdf, load_passwords().get(pdf.name)).statement
    finally:
        parallel.MIN_PAGES = old
    key = lambda st: [(t.date, t.debit, t.credit, t.balance, t.description) for t in st.transactions]  # noqa: E731
    assert key(fast) == key(slow) and len(fast.transactions) > 100


def test_bank_of_maharashtra_reads_its_cheque_and_reference_column():
    """The "Cheque / Reference No" column is headed on two lines around the main heading row."""
    from conftest import find_statement, load
    if find_statement("bankofmaharastrsa1.pdf") is None:
        pytest.skip("bankofmaharastrsa1.pdf not present")
    tx = load("bankofmaharastrsa1.pdf").statement.transactions
    assert sum(1 for t in tx if len(t.ref_no) == 12) > 40  # IMPS / UPI references
    assert sorted(t.cheque_no for t in tx if t.cheque_no) == ["1616", "1617"]  # the only real cheque numbers
