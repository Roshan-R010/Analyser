"""Block tables: the loan page's table style, reused by the cashflow and returns pages.

Every page after the summary shows blocks (a name, a grey line, a total on the right, then rows).
Only the columns change. A cell is {"t": text, "s": grey line under it, "c": css class};
a column is {"name", "c": css class, "w": width in %}.
"""
from __future__ import annotations

from decimal import Decimal

from analyser.fmt import inr, inr2
from analyser.sections.returns import FUNDS, TECHNICAL, UNKNOWN


def _count(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def cell(text, sub="", cls="") -> dict:
    return {"t": text, "s": sub, "c": cls}


def cols(*spec) -> list[dict]:
    return [{"name": n, "c": c, "w": w} for n, c, w in spec]


def io_line(tx) -> str:
    cr = sum((t.credit for t in tx), Decimal(0))
    dr = sum((t.debit for t in tx), Decimal(0))
    return " · ".join(x for x in (cr and f"In ₹{inr(cr)}", dr and f"Out ₹{inr(dr)}") if x)


# ---------------------------------------------------------------- cashflow

def cashflow_page(cf) -> dict:
    columns = cols(("Month", "", 15), ("Credit (₹)", "n", 13), ("Debit (₹)", "n", 13), ("Net cashflow (₹)", "n", 14),
                   ("Avg balance (₹)", "n", 14), ("Cr entries", "n", 9), ("Dr entries", "n", 9),
                   ("Chq/ECS returns", "n", 13))

    def row(label, r, sub="", returns=None, rounded=False):
        count = (lambda x: str(int(round(x)))) if rounded else (lambda x: str(int(x)))
        ret = cell(("NIL" if returns == 0 else str(returns)) if returns is not None else "–",
                   cls="n warn" if returns else "n")
        return {"cells": [cell(label, sub), cell(inr(r.credit), cls="n"), cell(inr(r.debit), cls="n"),
                          cell(inr(r.net), cls="n neg" if r.net < 0 else "n"),
                          cell(inr(r.avg_balance), cls="n neg" if r.avg_balance < 0 else "n"),
                          cell(count(r.cr_entries), cls="n"), cell(count(r.dr_entries), cls="n"), ret]}

    blocks = [
        {"title": "Month by month", "subline": _count(len(cf.months), "month"), "right": f"Net ₹{inr(cf.total.net)}",
         "rows": [row(m.label, m, returns=m.returns) for m in cf.months]},
        {"title": "Totals and averages", "subline": "whole statement period · the average row is per month", "right": "",
         "rows": [row("Total", cf.total, rounded=True), row("Monthly avg", cf.monthly_avg, rounded=True)]},
    ]
    rows = []
    for n in (3, 6, 9, 12):
        r = cf.last.get(n)
        if r:
            span = r.label.split("(")[1][:-1]
            short = f" · the statement has only {len(cf.months)} month{'s' if len(cf.months) != 1 else ''}" if n > len(cf.months) else ""
            rows.append(row(f"Last {n} months", r, sub=span + short, rounded=True))
        else:
            rows.append({"cells": [cell(f"Last {n} months"), {**cell("not enough months", cls="muted"), "span": 7}]})
    blocks.append({"title": "Recent months", "subline": "the last 3, 6, 9 and 12 months of the statement", "right": "",
                   "rows": rows})
    return {"cols": columns, "blocks": blocks}


# ---------------------------------------------------------------- returns

def returns_page(rs) -> dict:
    columns = cols(("Date", "", 10), ("Chq no", "", 10), ("Amount (₹)", "n", 13), ("Bank balance (₹)", "n", 14),
                   ("Reason", "", 18), ("Details", "", 35))
    blocks = []
    for kind, title, bad in ((FUNDS, "Returned for insufficient funds", True), (TECHNICAL, "Technical returns", False),
                             (UNKNOWN, "Returned · reason not stated", False)):
        bs = [b for b in rs.bounces if b.kind == kind]
        if not bs:
            continue
        rows = []
        for b in bs:
            sub = " · ".join(x for x in (b.direction,
                                          f"original payment {b.original.date:%d %b %Y}" if b.original else "",
                                          f"return charge ₹{inr2(b.charge_total)}" if b.charge_total else "",
                                          b.note) if x)
            rows.append({"cells": [cell(f"{b.date:%d %b %y}"), cell(b.cheque_no or "–"),
                                   cell(inr2(b.amount) if b.amount else "", cls="n amt"), cell(inr(b.balance), cls="n"),
                                   cell(b.reason or "–"), cell(b.description, sub)]})
        blocks.append({"title": title, "subline": _count(len(bs), "return"), "bad": bad,
                       "right": f"₹{inr(sum((b.amount or 0 for b in bs), Decimal(0)))}", "rows": rows})

    sent_cols = cols(("Date", "", 11), ("Amount (₹)", "n", 15), ("Bank balance (₹)", "n", 15), ("Details", "", 59))
    sent_blocks = []
    if rs.transfer_returns:
        txs = [x.txn for x in rs.transfer_returns]
        rows = [{"cls": "in" if x.txn.credit else "", "cells": [
            cell(f"{x.txn.date:%d %b %y}"),
            cell(f"+{inr2(x.txn.credit)}" if x.txn.credit else inr2(x.txn.debit), cls="n amt"),
            cell(inr(x.txn.balance), cls="n"), cell(x.txn.description, x.reason)]} for x in rs.transfer_returns]
        sent_blocks.append({"title": "Transfers sent back", "subline": _count(len(txs), "entry", "entries") + " · not cheque bounces",
                            "right": io_line(txs), "rows": rows})
    return {"cols": columns, "blocks": blocks, "sent_cols": sent_cols, "sent_blocks": sent_blocks}


# ---------------------------------------------------------------- suspicious statements

def suspicion_page(report) -> dict:
    """Where each suspicious statement stops adding up, in the block style of the other pages."""
    columns = cols(("Page", "", 6), ("Date", "", 10), ("Entry", "", 29), ("Balance before (₹)", "n", 12),
                   ("Entry (₹)", "n", 11), ("Should be (₹)", "n", 11), ("Printed (₹)", "n", 11),
                   ("Gap (₹)", "n", 10))
    blocks = []
    for s in report.suspicious:
        rows = []
        for f in s.findings:
            amount = f"+{inr2(f.credit)}" if f.credit else f"-{inr2(f.debit)}"
            rows.append({"cells": [
                cell(str(f.page_no)), cell(f"{f.date:%d %b %y}"), cell(f.description, f.hint),
                cell(inr2(f.previous), cls="n"), cell(amount, cls="n"), cell(inr2(f.expected), cls="n"),
                cell(inr2(f.printed) if f.printed is not None else "none printed", cls="n amt"),
                cell(inr2(f.difference) if f.difference is not None else "–", cls="n warn")]})
        more = f"+{s.more} more not listed" if s.more else ""
        title = f"Statement {s.statement_no} · {s.file_name}" if s.file_name else f"Statement {s.statement_no}"
        sub = (_count(s.breaks, "entry", "entries") + " out of " + str(s.rows) + " do not add up") if s.breaks \
            else " · ".join(s.problems)
        blocks.append({"title": title, "subline": sub, "right": more, "bad": True, "rows": rows})
    return {"cols": columns, "blocks": [b for b in blocks if b["rows"]]}
