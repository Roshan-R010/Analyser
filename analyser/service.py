"""What every front door needs, in two calls: read one statement file, make one borrower's report.

The command line, the Telegram bot (and later the website and WhatsApp) all use this, so a front door
only deals with its own chat or page. Nothing here prints or asks questions.

    read_file(path, password)   -> FileOutcome   (ok / needs password / wrong password / unreadable / rejected)
    make_report(loaded, out)    -> ReportResult  (the PDF and a short plain-text summary)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from analyser.engine import LoadedStatement, load_statement
from analyser.fmt import inr
from analyser.unlock import PasswordRequired, StatementError, WrongPassword

OK, NEEDS_PASSWORD, WRONG_PASSWORD, UNREADABLE, REJECTED = "ok", "needs_password", "wrong_password", "unreadable", "rejected"


@dataclass
class FileOutcome:
    status: str
    name: str
    message: str  # plain words for the person, safe to show
    loaded: LoadedStatement | None = None

    @property
    def ok(self) -> bool:
        return self.status == OK


@dataclass
class ReportResult:
    pdf: Path
    summary: str  # a few plain lines: who, when, money in/out, flags, checks
    all_checks_ok: bool


def read_file(path: str | Path, password: str | None = None) -> FileOutcome:
    """Read and balance-check one statement. A statement whose balances don't add up is REJECTED:
    it is never put in a report."""
    path = Path(path)
    try:
        loaded = load_statement(path, password, with_picture=True)
    except PasswordRequired:
        return FileOutcome(NEEDS_PASSWORD, path.name, "This statement is password protected.")
    except WrongPassword:
        return FileOutcome(WRONG_PASSWORD, path.name, "That password did not open the statement.")
    except StatementError as exc:
        return FileOutcome(UNREADABLE, path.name, str(exc))
    except Exception:  # a layout we cannot even start on must not take the front door down
        return FileOutcome(UNREADABLE, path.name, "This statement could not be read.")

    st = loaded.statement
    if loaded.supported:
        bank = st.bank.upper() if st.bank != "unknown" else "unrecognised bank"
        return FileOutcome(OK, path.name, f"{bank} · {st.period_from:%d %b %Y} to {st.period_to:%d %b %Y} · "
                                          f"{len(st.transactions)} entries, every balance adds up.", loaded)
    if not st.transactions:
        return FileOutcome(REJECTED, path.name, "No transactions could be read: this layout is not supported yet.", loaded)
    return FileOutcome(REJECTED, path.name,
                       "The balances in this statement do not add up, so it was left out. "
                       "It may have been edited, or its layout is not supported yet.", loaded)


def make_report(loaded: list[LoadedStatement], out_pdf: str | Path) -> ReportResult:
    """The report PDF for one borrower from statements that all passed `read_file`."""
    from analyser.analysis import analyse
    from analyser.report.render import write_report

    report = analyse(loaded)
    paths = write_report(report, Path(out_pdf))
    cf = report.cashflow
    first = min(s.statement.period_from for s in report.statements if s.statement.period_from)
    last = max(s.statement.period_to for s in report.statements if s.statement.period_to)
    lines = [
        f"{report.borrower}",
        f"{first:%d %b %Y} to {last:%d %b %Y} · {len(report.statements)} statement(s)",
        f"Money in ₹{inr(cf.total.credit)} · out ₹{inr(cf.total.debit)} · average balance ₹{inr(cf.total.avg_balance)}",
    ]
    lines += [f"{'⚠' if f.level in ('high', 'watch') else '•'} {f.text}" for f in report.flags[:5]]
    failed = [c for c in report.checks if not c.ok]
    lines.append(f"Checks: {len(report.checks) - len(failed)}/{len(report.checks)} passed")
    return ReportResult(pdf=paths["pdf"], summary="\n".join(lines), all_checks_ok=not failed)
