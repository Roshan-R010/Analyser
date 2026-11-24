"""Shared test helpers.

Real statements live in tests/statements/<bank>/ (one folder per bank profile id) and their
passwords in passwords.txt (by file name, so file names must be unique).
Both are private and never committed, so tests that need them skip when absent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATEMENTS = ROOT / "tests" / "statements"
EXPECTED = ROOT / "tests" / "expected"
PASSWORDS_FILE = ROOT / "passwords.txt"


def load_passwords() -> dict[str, str]:
    """Read `filename.pdf = password` lines from passwords.txt."""
    if not PASSWORDS_FILE.is_file():
        return {}
    out = {}
    for line in PASSWORDS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, pw = line.split("=", 1)
        out[name.strip()] = pw.strip()
    return out


@pytest.fixture(scope="session")
def passwords() -> dict[str, str]:
    return load_passwords()


def find_statement(name: str) -> Path | None:
    """A library statement by file name, wherever its bank folder is."""
    if (STATEMENTS / name).is_file():
        return STATEMENTS / name
    return next((p for p in STATEMENTS.rglob(name) if p.is_file()), None) if STATEMENTS.is_dir() else None


def library_pdfs(rejected: bool = False) -> list[Path]:
    """Every library statement. Those in a `rejected/` folder are statements whose own printed numbers
    don't add up: they must keep being refused, and are listed only with rejected=True."""
    if not STATEMENTS.is_dir():
        return []
    pdfs = (p for p in STATEMENTS.rglob("*") if p.suffix.lower() == ".pdf")
    return sorted(p for p in pdfs if (rejected or "rejected" not in p.parent.parts) and
                  (not rejected or "rejected" in p.parent.parts))


def statement(name: str) -> Path:
    path = find_statement(name)
    if path is None:
        pytest.skip(f"private statement {name} not present")
    return path


_loaded_cache: dict = {}


def load(name: str):
    """Read a library statement once per test run (ICICI alone is 124 pages).

    Each call returns a fresh copy, because analysis fills in fields on the transactions.
    """
    import copy

    from analyser.engine import load_statement

    if name not in _loaded_cache:
        _loaded_cache[name] = load_statement(statement(name), load_passwords().get(name))
    return copy.deepcopy(_loaded_cache[name])
