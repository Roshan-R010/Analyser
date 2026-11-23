"""Report -> HTML -> PDF (printed by headless Chromium), plus a JSON summary.

The JSON is what the website / WhatsApp front doors will use later.
"""
from __future__ import annotations

import base64
import json
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from analyser.analysis import Report
from analyser.profiles import load_profiles
from analyser.report import charts
from analyser.sections.flags import inr as _inr
from analyser.sections.loans import loan_blocks
from analyser.sections.returns import FUNDS

TEMPLATES = Path(__file__).parent / "templates"


def inr(x) -> str:
    return "–" if x is None else _inr(Decimal(x))


def inr2(x) -> str:
    """With paise only when there are paise: 30,851.88 / 42,432."""
    if x is None:
        return "–"
    x = Decimal(x)
    whole = x.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if x == whole:
        return _inr(whole)
    paise = f"{abs(x):.2f}".split(".")[1]
    head = _inr(x.copy_abs().to_integral_value(rounding="ROUND_FLOOR"))
    return ("-" if x < 0 else "") + f"{head}.{paise}"


def _or_blank(f):
    return lambda x: "" if not x else f(x)


def _d(x) -> str:
    return f"{x:%d %b %Y}" if x else "–"


def _bank_names() -> dict[str, str]:
    return {p.id: p.name for p in load_profiles()}


def _mask(acc: str) -> str:
    return f"XXXX{acc[-4:]}" if acc else "–"


def _amounts(pairs) -> str:
    shown = [f"{inr2(a)} ×{n}" if n > 1 else inr2(a) for a, n in pairs[:3]]
    more = len(pairs) - 3
    return ", ".join(shown) + (f", +{more} other amounts" if more > 0 else "")


def _dates(ds: list[date]) -> str:
    if len(ds) <= 12:
        return ", ".join(f"{d:%d %b}" for d in ds)
    per: dict[str, int] = {}
    for d in ds:
        per[f"{d:%b %y}"] = per.get(f"{d:%b %y}", 0) + 1
    return " · ".join(f"{m} ({n})" for m, n in per.items())


def _month_dates(ds: list[date], with_year: bool = False) -> str:
    """Aug 07, 14, 19 · Sep 01 (the year is in the column heading unless with_year)."""
    out: dict[str, list[str]] = {}
    for d in sorted(ds):
        out.setdefault(f"{d:%b %y}" if with_year else f"{d:%b}", []).append(f"{d:%d}")
    return " · ".join(f"{m} {', '.join(days)}" for m, days in out.items())


def _title(name: str) -> str:
    """RAMESH V -> Ramesh V; leaves mixed-case names alone."""
    return name.title() if name.isupper() else name


def _short_period(a: date | None, b: date | None) -> str:
    if not a or not b:
        return "–"
    left = f"{a:%d %b}" if a.year == b.year else f"{a:%d %b %Y}"
    return f"{left} – {b:%d %b %Y}"


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def _io(tx) -> str:
    cr = [t for t in tx if t.credit]
    dr = [t for t in tx if t.debit]
    bits = []
    if cr:
        bits.append(f"In ₹{inr(sum(t.credit for t in cr))}")
    if dr:
        bits.append(f"Out ₹{inr(sum(t.debit for t in dr))}")
    return " · ".join(bits)


def unknown_blocks(listed) -> list[dict]:
    """Unknown entries, one block per month."""
    by: dict[date, list] = {}
    for t in listed:
        by.setdefault(t.date.replace(day=1), []).append(t)
    out = []
    for m, tx in by.items():
        cr, dr = sum(1 for t in tx if t.credit), sum(1 for t in tx if t.debit)
        sub = " · ".join(x for x in (cr and _count(cr, "credit"), dr and _count(dr, "debit")) if x)
        out.append({"title": f"{m:%B %Y}", "subline": sub, "right": _io(tx),
                    "rows": [(t, t.description, t.mode) for t in tx]})
    return out


def cheque_blocks(cheques) -> list[dict]:
    """Cheques in number order, split into issued / deposited / returned."""
    groups = [
        ("Cheques issued", "paid out by the borrower", [t for t in cheques if t.debit and t.mode != "Return"]),
        ("Cheques deposited", "received by the borrower", [t for t in cheques if t.credit and t.mode != "Return"]),
        ("Cheque returns", "entries the bank marked as returned or reversed", [t for t in cheques if t.mode == "Return"]),
    ]
    out = []
    for title, what, tx in groups:
        if tx:
            total = sum(t.debit + t.credit for t in tx)
            out.append({"title": title, "subline": f"{_count(len(tx), 'cheque')} · {what}", "right": _io(tx),
                        "total": f"₹{inr(total)}",
                        "rows": [(t, t.party_clean or "Unknown", t.description) for t in tx], "bad": title == "Cheque returns"})
    return out


def _months(ms: list[date]) -> str:
    return ", ".join(f"{m:%b %y}" for m in ms) if ms else "–"


def render_html(r: Report, generated: datetime | None = None) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    env.filters.update(
        inr=inr, inr2=inr2, inr_or_blank=_or_blank(inr), inr2_or_blank=_or_blank(inr2), d=_d,
        mon=lambda m: f"{m:%B %Y}", b64=lambda b: base64.b64encode(b).decode("ascii"),
    )
    names = _bank_names()
    cf = r.cashflow
    labels = [f"{m.month:%b %y}" for m in cf.months]
    first = min((s.statement.period_from for s in r.statements if s.statement.period_from), default=None)
    last = max((s.statement.period_to for s in r.statements if s.statement.period_to), default=None)
    rec_dates = [d for x in r.recurring for d in x.dates]
    rec_years = sorted({d.year for d in rec_dates})
    loan_years = sorted({t.date.year for ln in r.loans for t in ln.entries})
    return env.get_template("report.html.j2").render(
        r=r, css=(TEMPLATES / "report.css").read_text(encoding="utf-8"),
        period=f"{_d(first)} – {_d(last)}", short_period=_short_period(first, last),
        accounts_line=" · ".join(f"{names.get(a.bank, a.bank.upper())} · Account ending {a.account_no[-4:]}"
                                 if a.account_no else names.get(a.bank, a.bank.upper()) for a in r.accounts),
        rec_year=str(rec_years[0]) if len(rec_years) == 1 else "",
        month_dates=_month_dates, title=_title,
        unknown_blocks=unknown_blocks(r.unknown.listed), cheque_blocks=cheque_blocks(r.cheques),
        all_year=str(first.year) if first and last and first.year == last.year else "",
        loan_blocks=loan_blocks(r.loans), loan_year=str(loan_years[0]) if len(loan_years) == 1 else "",
        loan_paid=sum((ln.paid_total for ln in r.loans), Decimal(0)),
        loan_received=sum((ln.received_total for ln in r.loans), Decimal(0)),
        loan_emis=[ln.emi for ln in r.loans if ln.emi and ln.payments],
        loan_has_chit=any(ln.type == "Chit fund" and ln.payments for ln in r.loans),
        generated=f"{(generated or datetime.now()):%d %b %Y, %I:%M %p}",
        bank_name=lambda b: names.get(b, b.upper()), mask=_mask, amounts=_amounts, dates=_dates, months=_months,
        funds_count=sum(1 for b in r.returns.bounces if b.kind == FUNDS),
        chart_bars=charts.bars_in_out(labels, [m.credit for m in cf.months], [m.debit for m in cf.months]),
        chart_line=charts.line_balance(labels, [m.avg_balance for m in cf.months]),
        chart_modes_in=charts.mode_bars(r.modes_in, charts.BLUE),
        chart_modes_out=charts.mode_bars(r.modes_out, charts.ORANGE),
    )


_CHROME = ('width:100%;font-size:7px;color:#7a7974;padding:0 11mm;display:flex;'
           'justify-content:space-between;font-family:Inter,Segoe UI,Arial,sans-serif')
HEADER = (f'<div style="{_CHROME};letter-spacing:.06em;text-transform:uppercase;font-weight:600">'
          '<span style="color:#0b0b0b">{who}</span><span>Bank statement analysis</span></div>')
FOOTER = (f'<div style="{_CHROME}">'
          '<span>{who} · Statement analysis · computer-generated</span>'
          '<span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>')


def print_pdf(html: str, out: Path, borrower: str = "") -> Path:
    from playwright.sync_api import sync_playwright

    out = Path(out)
    who = borrower.replace("<", "").replace("&", "and")
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="load")
        page.pdf(path=str(out), format="A4", print_background=True,
                 margin={"top": "14mm", "bottom": "13mm", "left": "11mm", "right": "11mm"},
                 display_header_footer=True, header_template=HEADER.format(who=who),
                 footer_template=FOOTER.format(who=who))
        browser.close()
    return out


def summary_json(r: Report) -> dict:
    """The key numbers, for the website / WhatsApp front doors."""
    def num(x):
        return None if x is None else str(x)
    cf = r.cashflow
    return {
        "borrower": r.borrower,
        "all_checks_ok": r.all_checks_ok,
        "statements": [{"no": s.statement.statement_no, "bank": s.statement.bank,
                        "account": _mask(s.statement.account_no),
                        "from": num(s.statement.period_from), "to": num(s.statement.period_to),
                        "transactions": len(s.statement.transactions)} for s in r.statements],
        "totals": {"credit": num(cf.total.credit), "debit": num(cf.total.debit),
                   "avg_balance": num(cf.total.avg_balance.quantize(Decimal("0.01")))},
        "months": [{"month": f"{m.month:%Y-%m}", "credit": num(m.credit), "debit": num(m.debit),
                    "avg_balance": num(m.avg_balance.quantize(Decimal("0.01"))),
                    "cr_entries": int(m.cr_entries), "dr_entries": int(m.dr_entries), "returns": m.returns}
                   for m in cf.months],
        "bounces": [{"date": num(b.date), "cheque_no": b.cheque_no, "amount": num(b.amount),
                     "kind": b.kind, "reason": b.reason} for b in r.returns.bounces],
        "loans": [{"lender": ln.lender, "type": ln.type, "emi": num(ln.emi), "paid": num(ln.paid_total),
                   "received": num(ln.received_total), "missed": [f"{m:%Y-%m}" for m in ln.months_missed]}
                  for ln in r.loans],
        "flags": [{"level": f.level, "text": f.text} for f in r.flags],
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in r.checks],
    }


def write_report(r: Report, out_pdf: Path, html_copy: bool = False) -> dict[str, Path]:
    html = render_html(r)
    out_pdf = Path(out_pdf)
    paths = {"pdf": print_pdf(html, out_pdf, r.borrower)}
    js = out_pdf.with_suffix(".json")
    js.write_text(json.dumps(summary_json(r), indent=2), encoding="utf-8")
    paths["json"] = js
    if html_copy:
        h = out_pdf.with_suffix(".html")
        h.write_text(html, encoding="utf-8")
        paths["html"] = h
    return paths
