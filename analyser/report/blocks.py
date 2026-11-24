"""Block tables: the loan page's table style, reused by the cashflow and returns pages.

Every page after the summary shows blocks (a name, a grey line, a total on the right, then rows).
Only the columns change. A cell is {"t": text, "s": grey line under it, "c": css class};
a column is {"name", "c": css class, "w": width in %}.
"""
from __future__ import annotations

from decimal import Decimal

from analyser.sections.flags import inr as _inr
from analyser.sections.returns import FUNDS, TECHNICAL, UNKNOWN


def inr(x) -> str:
    return "–" if x is None else _inr(Decimal(x))


def inr2(x) -> str:
    """With paise only when there are paise: 30,851.88 / 42,432."""
    if x is None:
        return "–"
    x = Decimal(x)
    if x == x.to_integral_value():
        return _inr(x.quantize(Decimal("1")))
    head = _inr(x.copy_abs().to_integral_value(rounding="ROUND_FLOOR"))
    return ("-" if x < 0 else "") + f"{head}.{f'{abs(x):.2f}'.split('.')[1]}"


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
            rows.append(row(f"Last {n} months", r, sub=r.label.split("(")[1][:-1], rounded=True))
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
