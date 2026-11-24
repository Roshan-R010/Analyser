"""Make a statement analysis report from one or more bank statement PDFs (one borrower).

Usage:
    .venv/Scripts/python cli.py statement.pdf
    .venv/Scripts/python cli.py jan-oct.pdf nov.pdf --out reports/borrower.pdf
    .venv/Scripts/python cli.py locked.pdf --password 1234
    .venv/Scripts/python cli.py statement.pdf --check-only        (read + balance check, no report)
    .venv/Scripts/python cli.py statement.pdf --check-only --csv  (also save the transactions as CSV)

Passwords: --password (used for every file), else passwords.txt, else it asks.
A statement whose balances don't all add up is left out of the report, never shown wrong.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import sys
import time
from pathlib import Path

from analyser.engine import LoadedStatement, load_statement
from analyser.fmt import inr_paise as inr
from analyser.model import ZERO
from analyser.unlock import PasswordRequired, StatementError, WrongPassword

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"


def saved_password(pdf: Path) -> str | None:
    f = ROOT / "passwords.txt"
    if not f.is_file():
        return None
    for line in f.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            name, pw = line.split("=", 1)
            if name.strip().lower() == pdf.name.lower():
                return pw.strip()
    return None


def open_one(pdf: Path, password: str | None, with_picture: bool) -> LoadedStatement | None:
    password = password or saved_password(pdf)
    for _ in range(3):
        try:
            return load_statement(pdf, password, with_picture=with_picture)
        except (PasswordRequired, WrongPassword) as exc:
            if not sys.stdin.isatty():
                print(f"  {exc}. Give it with --password or in passwords.txt.")
                return None
            print(f"  {exc}.")
            password = getpass.getpass(f"  Password for {pdf.name}: ")
        except StatementError as exc:
            print(f"  Could not open: {exc}")
            return None
    print(f"  Giving up on {pdf.name} after 3 tries.")
    return None


def describe(ls: LoadedStatement) -> None:
    st, check = ls.statement, ls.check
    tx = st.transactions
    print(f"  {ls.file_name}: {st.bank.upper()}  {st.account_holder or '?'}  "
          f"{st.period_from} to {st.period_to}  {len(tx)} entries")
    if tx:
        print(f"     opening {inr(st.opening_balance)}  in {inr(sum((t.credit for t in tx), ZERO))}  "
              f"out {inr(sum((t.debit for t in tx), ZERO))}  closing {inr(tx[-1].balance)}")
    if check.ok:
        print(f"     balance check PASSED ({check.rows_checked} rows)")
    else:
        print("     balance check FAILED: format not supported yet, so this statement is left out")
        for b in check.breaks[:5]:
            print(f"       page {b.page_no}, {b.date}: expected {inr(b.expected)}, "
                  f"statement shows {inr(b.printed)}  | {b.description[:50]}")
        for p in check.problems:
            print(f"       {p}")


def write_csv(ls: LoadedStatement) -> Path:
    OUT.mkdir(exist_ok=True)
    out = OUT / f"{Path(ls.file_name).stem}_transactions.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel reads it right
        w = csv.writer(f)
        w.writerow(["#", "Page", "Date", "Value date", "Description", "Ref no", "Cheque no",
                    "Debit", "Credit", "Balance"])
        for i, t in enumerate(ls.statement.transactions, 1):
            w.writerow([i, t.page_no, t.date.strftime("%d-%m-%Y"),
                        t.value_date.strftime("%d-%m-%Y") if t.value_date else "",
                        t.description, t.ref_no, t.cheque_no, t.debit or "", t.credit or "", t.balance])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Bank statement analysis report")
    ap.add_argument("pdfs", type=Path, nargs="+", help="statement PDFs of one borrower")
    ap.add_argument("--password", help="password for the PDF(s)")
    ap.add_argument("--out", type=Path, help="report PDF path (default: out/<borrower>_report.pdf)")
    ap.add_argument("--check-only", action="store_true", help="only read and balance-check")
    ap.add_argument("--csv", action="store_true", help="with --check-only: also save transactions as CSV")
    ap.add_argument("--html", action="store_true", help="also save the report as HTML")
    ap.add_argument("--json", action="store_true", help="also save the key numbers as JSON")
    args = ap.parse_args()

    t0 = time.time()
    print("Reading statements...")
    loaded = []
    for pdf in args.pdfs:
        ls = open_one(pdf, args.password, with_picture=not args.check_only)
        if ls:
            describe(ls)
            loaded.append(ls)
            if args.csv and ls.statement.transactions:
                print(f"     saved {write_csv(ls)}")
    good = [ls for ls in loaded if ls.supported]
    if args.check_only:
        return 0 if good and len(good) == len(args.pdfs) else 2
    if not good:
        print("No statement could be read correctly; no report made.")
        return 2

    from analyser.analysis import analyse
    from analyser.report.render import write_report

    print("Analysing...")
    report = analyse(good)
    out = args.out or OUT / f"{_safe(report.borrower)}_report.pdf"
    paths = write_report(report, out, html_copy=args.html, json_copy=args.json)
    print("\nFlags:")
    for f in report.flags:
        print(f"  [{f.level}] {f.text}")
    bad = [c for c in report.checks if not c.ok]
    print(f"\nChecks: {len(report.checks) - len(bad)}/{len(report.checks)} passed")
    for c in bad:
        print(f"  FAILED {c.name}: {c.detail}")
    print(f"\nReport: {paths['pdf']}")
    if "json" in paths:
        print(f"Summary: {paths['json']}")
    if len(good) < len(args.pdfs):
        print(f"Note: {len(args.pdfs) - len(good)} statement(s) left out (see above).")
    print(f"Done in {time.time() - t0:.1f}s")
    return 0 if report.all_checks_ok else 3


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_")[:60] or "report"


if __name__ == "__main__":
    sys.exit(main())
