"""Make a report for every account in the statement library (one report per bank account).

Usage:  .venv/Scripts/python tools/make_reports.py [bank ...]

Statements of one account (same bank and account number) go into one report, as a borrower's
several statements would. Reports are written to out/library/<bank>/. Prints one line per report:
the checks it passed and the flags it raised, so a bank whose report looks wrong stands out.
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]


def main(banks: list[str]) -> int:
    from analyser.analysis import analyse
    from analyser.engine import load_statement
    from analyser.report.render import write_report
    from conftest import library_pdfs, load_passwords

    passwords = load_passwords()
    accounts: dict[tuple[str, str], list] = defaultdict(list)
    for pdf in library_pdfs():
        if banks and pdf.parent.name not in banks:
            continue
        loaded = load_statement(pdf, passwords.get(pdf.name), with_picture=True)
        if not loaded.reportable:
            print(f"SKIPPED {pdf.name}: layout not supported or balances do not add up on most rows")
            continue
        st = loaded.statement
        accounts[(pdf.parent.name, st.account_no or pdf.stem)].append(loaded)

    failures = 0
    for (bank, account), statements in sorted(accounts.items()):
        started = time.time()
        report = analyse(statements)
        out = ROOT / "out" / "library" / bank / f"{bank}_{account[-4:]}.pdf"
        out.parent.mkdir(parents=True, exist_ok=True)
        write_report(report, out)
        bad = [c for c in report.checks if not c.ok]
        failures += bool(bad)
        entries = sum(len(s.statement.transactions) for s in statements)
        print(f"{bank:12} {account[-6:]:>6}  {len(statements)} statement(s) {entries:5} entries  "
              f"checks {len(report.checks) - len(bad)}/{len(report.checks)}  flags {len(report.flags)}  "
              f"{time.time() - started:4.1f}s  {out.relative_to(ROOT)}", flush=True)
        for c in bad:
            print(f"     FAILED {c.name}: {c.detail}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
