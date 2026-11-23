"""Charts as inline SVG (printed in the PDF, so no hover layer).

Colours: the validated reference palette (blue = money in, orange = money out, an
adjacent pair that passes the colour-blind checks). Thin marks, rounded data ends
anchored to the baseline, a 2px gap between neighbouring bars, recessive grid.
Every chart has its numbers in a table elsewhere in the report.
"""
from __future__ import annotations

from decimal import Decimal
from html import escape

BLUE, ORANGE = "#2a78d6", "#eb6834"
GRID, AXIS, INK2, INK3 = "#e6e5e1", "#c9c8c2", "#52514e", "#7a7974"
FONT = "font-family:Inter,Segoe UI,Arial,sans-serif"


def short_inr(x: float) -> str:
    """Axis labels in lakh / crore: 2.5L, 1.2Cr."""
    a = abs(x)
    sign = "-" if x < 0 else ""
    if a >= 1e7:
        return f"{sign}{a / 1e7:.1f}Cr".replace(".0Cr", "Cr")
    if a >= 1e5:
        return f"{sign}{a / 1e5:.1f}L".replace(".0L", "L")
    if a >= 1e3:
        return f"{sign}{a / 1e3:.0f}K"
    return f"{sign}{a:.0f}"


def _nice_max(v: float) -> float:
    if v <= 0:
        return 1.0
    import math
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if m * exp >= v:
            return m * exp
    return 10 * exp


def _bar_path(x: float, y_top: float, w: float, base: float, r: float = 3.0) -> str:
    """Bar with rounded top corners only (anchored flat to the baseline)."""
    h = base - y_top
    if h <= 0:
        return ""
    r = min(r, w / 2, h)
    return (f"M{x:.1f},{base:.1f} V{y_top + r:.1f} Q{x:.1f},{y_top:.1f} {x + r:.1f},{y_top:.1f} "
            f"H{x + w - r:.1f} Q{x + w:.1f},{y_top:.1f} {x + w:.1f},{y_top + r:.1f} V{base:.1f} Z")


def bars_in_out(labels: list[str], credit: list[Decimal], debit: list[Decimal],
                width: int = 700, height: int = 230) -> str:
    left, right, top, bottom = 52, 10, 26, 28
    pw, ph = width - left - right, height - top - bottom
    vmax = _nice_max(float(max(credit + debit, default=0)))
    n = max(1, len(labels))
    slot = pw / n
    bw = min(22.0, (slot - 10) / 2)
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
           f'aria-label="Money in and out by month" style="{FONT}">']
    for i in range(5):
        v = vmax * i / 4
        y = top + ph - ph * i / 4
        out.append(f'<line x1="{left}" x2="{width - right}" y1="{y:.1f}" y2="{y:.1f}" '
                   f'stroke="{GRID if i else AXIS}" stroke-width="1"/>')
        out.append(f'<text x="{left - 6}" y="{y + 3.5:.1f}" text-anchor="end" font-size="9.5" '
                   f'fill="{INK3}">{short_inr(v)}</text>')
    base = top + ph
    for i, lab in enumerate(labels):
        cx = left + slot * i + slot / 2
        for j, (val, col) in enumerate(((credit[i], BLUE), (debit[i], ORANGE))):
            x = cx - bw - 1 + j * (bw + 2)  # 2px gap between the pair
            y = base - ph * float(val) / vmax
            p = _bar_path(x, y, bw, base)
            if p:
                out.append(f'<path d="{p}" fill="{col}"><title>{escape(lab)} '
                           f'{"in" if j == 0 else "out"}: {short_inr(float(val))}</title></path>')
        out.append(f'<text x="{cx:.1f}" y="{height - 10}" text-anchor="middle" font-size="9.5" '
                   f'fill="{INK2}">{escape(lab)}</text>')
    # Legend (two series): top right
    lx = width - right - 150
    for k, (name, col) in enumerate((("Money in", BLUE), ("Money out", ORANGE))):
        out.append(f'<rect x="{lx + k * 78}" y="6" width="10" height="10" rx="2" fill="{col}"/>'
                   f'<text x="{lx + k * 78 + 14}" y="14.5" font-size="10" fill="{INK2}">{name}</text>')
    out.append("</svg>")
    return "".join(out)


def line_balance(labels: list[str], values: list[Decimal], width: int = 700, height: int = 200) -> str:
    left, right, top, bottom = 52, 14, 14, 28
    pw, ph = width - left - right, height - top - bottom
    vals = [float(v) for v in values]
    vmax = _nice_max(max(vals + [0]))
    vmin = min(0.0, min(vals + [0]))
    if vmin < 0:
        vmin = -_nice_max(-vmin)
    span = (vmax - vmin) or 1
    n = max(1, len(labels))
    pad = 24  # keep the first and last points (and their labels) off the edges
    step = (pw - 2 * pad) / max(1, n - 1) if n > 1 else 0

    def y(v: float) -> float:
        return top + ph - ph * (v - vmin) / span

    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
           f'aria-label="Average balance by month" style="{FONT}">']
    for i in range(5):
        v = vmin + span * i / 4
        out.append(f'<line x1="{left}" x2="{width - right}" y1="{y(v):.1f}" y2="{y(v):.1f}" '
                   f'stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{left - 6}" y="{y(v) + 3.5:.1f}" text-anchor="end" font-size="9.5" '
                   f'fill="{INK3}">{short_inr(v)}</text>')
    out.append(f'<line x1="{left}" x2="{width - right}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="{AXIS}"/>')
    xs = [left + (pad + step * i if n > 1 else pw / 2) for i in range(n)]
    pts = " ".join(f"{x:.1f},{y(v):.1f}" for x, v in zip(xs, vals))
    if n > 1:
        out.append(f'<polyline points="{pts}" fill="none" stroke="{BLUE}" stroke-width="2" '
                   f'stroke-linejoin="round" stroke-linecap="round"/>')
    for x, v, lab in zip(xs, vals, labels):
        out.append(f'<circle cx="{x:.1f}" cy="{y(v):.1f}" r="4" fill="{BLUE}" stroke="#fff" stroke-width="2">'
                   f'<title>{escape(lab)}: {short_inr(v)}</title></circle>')
        out.append(f'<text x="{x:.1f}" y="{height - 10}" text-anchor="middle" font-size="9.5" '
                   f'fill="{INK2}">{escape(lab)}</text>')
    # Label only the highest and lowest points (selective direct labels)
    if vals:
        for idx in {vals.index(max(vals)), vals.index(min(vals))}:
            above = idx == vals.index(max(vals))
            out.append(f'<text x="{xs[idx]:.1f}" y="{y(vals[idx]) + (-9 if above else 15):.1f}" '
                       f'text-anchor="middle" font-size="9.5" fill="{INK2}">{short_inr(vals[idx])}</text>')
    out.append("</svg>")
    return "".join(out)


def mode_bars(rows: list, color: str, width: int = 340) -> str:
    """Horizontal percentage bars, one per payment mode (rows: ModeShare)."""
    row_h, label_w, pct_w = 19, 78, 44
    height = row_h * max(1, len(rows)) + 4
    bar_w = width - label_w - pct_w
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="Share by payment mode" '
           f'style="{FONT}">']
    for i, r in enumerate(rows):
        yy = 2 + i * row_h
        w = bar_w * float(r.percent) / 100
        out.append(f'<text x="{label_w - 6}" y="{yy + 12}" text-anchor="end" font-size="10" '
                   f'fill="{INK2}">{escape(r.mode)}</text>')
        out.append(f'<rect x="{label_w}" y="{yy + 3}" width="{bar_w}" height="11" rx="2" fill="#f0efec"/>')
        if w > 0.5:
            out.append(f'<rect x="{label_w}" y="{yy + 3}" width="{max(w, 2):.1f}" height="11" rx="2" '
                       f'fill="{color}"/>')
        out.append(f'<text x="{width - 2}" y="{yy + 12}" text-anchor="end" font-size="10" '
                   f'fill="#0b0b0b">{float(r.percent):.1f}%</text>')
    out.append("</svg>")
    return "".join(out)
