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
    missing = [p.name for p in library_pdfs() if not (EXPECTED / (p.stem + ".yaml")).is_file()]
    names = [p.name.lower() for p in library_pdfs()]
    assert len(names) == len(set(names)), "two statements share a file name (passwords and expected files go by name)"
    assert not missing, f"run tools/make_expected.py for: {missing}"
