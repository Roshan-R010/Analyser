"""Write the expected-totals file for a statement in the test library.

Usage:  .venv/Scripts/python tools/make_expected.py KVB.pdf [more.pdf ...]

Refuses if the statement's balances don't all add up. Check the numbers it prints
against the statement (opening, closing, transaction count) before trusting it.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import yaml  # noqa: E402

from analyser.engine import load_statement  # noqa: E402
from analyser.model import ZERO  # noqa: E402
from conftest import EXPECTED, STATEMENTS, load_passwords  # noqa: E402


def summarise(loaded) -> dict:
    st = loaded.statement
    tx = st.transactions
    return {
        "bank": st.bank,
        "transactions": len(tx),
        "opening_balance": str(st.opening_balance),
        "closing_balance": str(tx[-1].balance) if tx else None,
        "total_debit": str(sum((t.debit for t in tx), ZERO)),
        "total_credit": str(sum((t.credit for t in tx), ZERO)),
        "debit_count": sum(1 for t in tx if t.debit),
        "credit_count": sum(1 for t in tx if t.credit),
        "with_cheque_no": sum(1 for t in tx if t.cheque_no),
        "period_from": str(st.period_from),
        "period_to": str(st.period_to),
    }


def main(names: list[str]) -> int:
    passwords = load_passwords()
    EXPECTED.mkdir(parents=True, exist_ok=True)
    failed = 0
    for name in names:
        loaded = load_statement(STATEMENTS / name, passwords.get(name))
        if not loaded.supported:
            failed += 1
            c = loaded.check
            print(f"{name}: NOT written. Balance check failed "
                  f"({len(c.breaks)} breaks, problems: {c.problems}). Fix the reader first.")
            continue
        data = summarise(loaded)
        out = EXPECTED / (Path(name).stem + ".yaml")
        out.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        print(f"{name}: written {out.relative_to(ROOT)}")
        for k, v in data.items():
            print(f"   {k}: {v}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
