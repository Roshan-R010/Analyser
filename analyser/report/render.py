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
    return env.get_template("report.html.j2").render(
        r=r, css=(TEMPLATES / "report.css").read_text(encoding="utf-8"),
        period=f"{_d(first)} – {_d(last)}", generated=f"{(generated or datetime.now()):%d %b %Y, %I:%M %p}",
        bank_name=lambda b: names.get(b, b.upper()), mask=_mask, amounts=_amounts, dates=_dates, months=_months,
        funds_count=sum(1 for b in r.returns.bounces if b.kind == FUNDS),
        chart_bars=charts.bars_in_out(labels, [m.credit for m in cf.months], [m.debit for m in cf.months]),
        chart_line=charts.line_balance(labels, [m.avg_balance for m in cf.months]),
        chart_modes_in=charts.mode_bars(r.modes_in, charts.BLUE),
        chart_modes_out=charts.mode_bars(r.modes_out, charts.ORANGE),
    )


FOOTER = ('<div style="width:100%;font-size:7px;color:#7a7974;padding:0 12mm;display:flex;'
          'justify-content:space-between;font-family:Segoe UI,Arial,sans-serif">'
          '<span>{who} · Statement Analysis · computer-generated</span>'
          '<span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>')


def print_pdf(html: str, out: Path, borrower: str = "") -> Path:
    from playwright.sync_api import sync_playwright

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="load")
        page.pdf(path=str(out), format="A4", print_background=True,
                 margin={"top": "11mm", "bottom": "13mm", "left": "11mm", "right": "11mm"},
                 display_header_footer=True, header_template="<span></span>",
                 footer_template=FOOTER.format(who=borrower.replace("<", "").replace("&", "and")))
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
