#!/usr/bin/env python3
"""Render a QC metrics JSON as a single self-contained HTML page.

Takes the JSON from qc_metrics.py and nothing else. It never opens the store, so
it cannot disagree with the numbers that were measured, and it needs no
dependencies at all -- standard library only, no numpy, no plotting library. That
means it can run anywhere, and that a rendering change can never alter a
measurement.

Charts are inline SVG built here rather than by a plotting library. The report has
to survive being emailed, copied off a cluster and opened with no network, so
every byte is in the file: no CDN, no external font, no script tag pointing
anywhere. A plotting library would either add a container dependency or a remote
script, and both fail that test.

Design rules this follows, which are not arbitrary:

- Fifteen channels is past the point where colour can carry identity, so
  per-channel data is a table with a supporting sparkline rather than fifteen
  coloured series. Colour is used for magnitude and for status, never to tell
  channels apart.
- Single-hue bars. Colouring each bar darker-where-longer would encode the same
  number twice and waste the only free channel.
- Every chart has a table underneath it. Nothing in this report is readable only
  by looking at a colour.
- The palette, both modes, is validated rather than chosen by eye: the categorical
  slot passes the lightness, chroma and contrast checks on both surfaces, and the
  five heatmap steps pass monotonic lightness, adjacent lightness separation,
  light-end contrast and single-hue.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------------
# Palette. Light and dark are both deliberate: the dark column is the same hues
# re-stepped for the dark surface, not an automatic inversion of the light one.
# --------------------------------------------------------------------------------

LIGHT = {
    "surface": "#fcfcfb",
    "plane": "#f9f9f7",
    "ink": "#0b0b0b",
    "ink2": "#52514e",
    "muted": "#898781",
    "grid": "#e1e0d9",
    "axis": "#c3c2b7",
    "border": "rgba(11,11,11,0.10)",
    "series": "#2a78d6",
    "wash": "#9ec5f4",
    "heat": ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"],
    "heat_ink": ["#0b0b0b", "#0b0b0b", "#ffffff", "#ffffff", "#ffffff"],
    "div": ["#104281", "#2a78d6", "#9ec5f4", "#f0efec", "#f0a3a3", "#d03b3b", "#8f1f1f"],
    "div_ink": ["#ffffff", "#ffffff", "#0b0b0b", "#0b0b0b", "#0b0b0b", "#ffffff", "#ffffff"],
}

DARK = {
    "surface": "#1a1a19",
    "plane": "#0d0d0d",
    "ink": "#ffffff",
    "ink2": "#c3c2b7",
    "muted": "#898781",
    "grid": "#2c2c2a",
    "axis": "#383835",
    "border": "rgba(255,255,255,0.10)",
    "series": "#3987e5",
    "wash": "#256abf",
    "heat": ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#b7d3f6"],
    "heat_ink": ["#ffffff", "#ffffff", "#0b0b0b", "#0b0b0b", "#0b0b0b"],
    "div": ["#9ec5f4", "#3987e5", "#1c5cab", "#383835", "#8f1f1f", "#d03b3b", "#f0a3a3"],
    "div_ink": ["#0b0b0b", "#0b0b0b", "#ffffff", "#ffffff", "#ffffff", "#ffffff", "#0b0b0b"],
}

# Fixed in both modes, and never reused for a series. Each one always ships with a
# glyph and a word, because two of them are below 3:1 on the light surface by
# design and colour must not be carrying the meaning on its own.
STATUS = {"good": "#0ca30c", "warning": "#fab219", "critical": "#d03b3b"}
GLYPH = {"good": "&#10003;", "warning": "&#9888;", "critical": "&#10007;"}


def esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def compact(n: float) -> str:
    """1284 -> 1,284 and 142493 -> 142.5K. For stat tiles, which have no room."""
    n = float(n)
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if abs(n) >= 10_000:
        return f"{n / 1000:.1f}K"
    if n == int(n):
        return f"{int(n):,}"
    return f"{n:,.1f}"


def thousands(n: float) -> str:
    return f"{int(round(float(n))):,}"


def nice_ticks(upper: float, count: int = 4) -> list[float]:
    """Round axis ticks from 0 to at least `upper`: 0, 1000, 2000, not 0, 1137, 2274.

    Axis ticks carry every value that is not directly labelled, so they have to be
    readable numbers.

    The last tick is always greater than or equal to `upper`, and that is load
    bearing rather than tidy. Callers scale marks by `ticks[-1]`, so a final tick
    below the data makes a mark longer than the plot: with a peak of 5400 an earlier
    version returned 0/2500/5000, and the tallest column came out 202px tall in a
    150px plot, escaping the SVG and drawing over the paragraph above it.
    """
    if upper <= 0:
        return [0.0]
    raw = upper / count
    magnitude = 10 ** math.floor(math.log10(raw))
    for step in (1, 2, 2.5, 5, 10):
        if raw <= step * magnitude:
            nice = step * magnitude
            break
    else:
        nice = 10 * magnitude
    ticks = [0.0]
    while ticks[-1] < upper - nice * 1e-9:
        ticks.append(round(ticks[-1] + nice, 10))
    return ticks


def bar_path(x: float, y: float, width: float, height: float, radius: float = 4.0) -> str:
    """A horizontal bar: square where it meets the baseline, rounded at the value end.

    The rounding marks which end is the data end. A fully rounded bar reads as a
    pill and loses that, and a fully square one reads as a table cell.
    """
    r = max(0.0, min(radius, width, height / 2))
    if width <= 0:
        return ""
    return (
        f"M{x:.1f},{y:.1f} H{x + width - r:.1f} "
        f"A{r:.1f},{r:.1f} 0 0 1 {x + width:.1f},{y + r:.1f} "
        f"V{y + height - r:.1f} "
        f"A{r:.1f},{r:.1f} 0 0 1 {x + width - r:.1f},{y + height:.1f} "
        f"H{x:.1f} Z"
    )


def column_path(x: float, y: float, width: float, height: float, radius: float = 4.0) -> str:
    """A vertical column: square at the baseline, rounded on the cap."""
    r = max(0.0, min(radius, width / 2, height))
    if height <= 0:
        return ""
    return (
        f"M{x:.1f},{y + height:.1f} V{y + r:.1f} "
        f"A{r:.1f},{r:.1f} 0 0 1 {x + r:.1f},{y:.1f} "
        f"H{x + width - r:.1f} "
        f"A{r:.1f},{r:.1f} 0 0 1 {x + width:.1f},{y + r:.1f} "
        f"V{y + height:.1f} Z"
    )


def sparkline(counts: list[int], width: float = 108.0, height: float = 24.0) -> str:
    """A filled shape of one channel's intensity distribution.

    Square-rooted, and the column header says so. Pixel-intensity histograms are
    dominated by the near-zero bin -- on real data the first bin holds 80% of the
    pixels -- so a linear sparkline is a single spike and every channel looks
    identical. The x range is 0 to p99.9 for the same reason, which the header also
    says. This is shape only; every number it hints at is a column in the same row.
    """
    if not counts or max(counts) == 0:
        return f'<svg class="spark" width="{width}" height="{height}" aria-hidden="true"></svg>'

    scaled = [math.sqrt(c) for c in counts]
    peak = max(scaled)
    step = width / len(scaled)
    points = [f"0,{height:.1f}"]
    for i, v in enumerate(scaled):
        points.append(f"{i * step:.2f},{height - (v / peak) * height:.2f}")
        points.append(f"{(i + 1) * step:.2f},{height - (v / peak) * height:.2f}")
    points.append(f"{width:.1f},{height:.1f}")
    return (
        f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'aria-hidden="true"><polygon points="{" ".join(points)}" fill="var(--wash)"/></svg>'
    )


def hbar_chart(
    rows: list[tuple[str, float]],
    unit: str,
    fmt,
    label_extreme: bool = True,
) -> str:
    """Horizontal single-hue bars, one row per channel.

    One hue for every bar: the length is the magnitude, so tinting by size would
    say it twice. Only the largest bar is directly labelled -- a number on all
    fifteen is noise, and the axis plus the table carry the rest.
    """
    if not rows:
        return ""
    label_w, right_pad, row_h, bar_h = 96.0, 44.0, 22.0, 13.0
    axis_band = 26.0
    plot_w = 700.0
    height = row_h * len(rows) + axis_band
    total_w = label_w + plot_w + right_pad
    upper = max((v for _, v in rows), default=0.0)
    ticks = nice_ticks(upper if upper > 0 else 1.0)
    scale = plot_w / (ticks[-1] if ticks[-1] else 1.0)
    peak = max(range(len(rows)), key=lambda i: rows[i][1]) if label_extreme else -1

    out = [
        f'<svg class="chart" viewBox="0 0 {total_w:.0f} {height:.0f}" width="100%" '
        f'height="{height:.0f}" role="img" preserveAspectRatio="xMinYMid meet">'
    ]
    for t in ticks:
        x = label_w + t * scale
        out.append(
            f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{row_h * len(rows):.1f}" '
            f'stroke="var(--grid)" stroke-width="1"/>'
        )
        out.append(
            f'<text class="tick" x="{x:.1f}" y="{row_h * len(rows) + 16:.0f}" '
            f'text-anchor="middle">{esc(fmt(t))}</text>'
        )
    for i, (name, value) in enumerate(rows):
        y = i * row_h + (row_h - bar_h) / 2
        w = max(0.0, value * scale)
        out.append(
            f'<text class="rowlabel" x="{label_w - 8:.0f}" y="{y + bar_h - 2:.1f}" '
            f'text-anchor="end">{esc(name)}</text>'
        )
        out.append(
            f'<path d="{bar_path(label_w, y, w, bar_h)}" fill="var(--series)" '
            f'tabindex="0" data-tip="{esc(name)}: {esc(fmt(value))} {esc(unit)}"/>'
        )
        if i == peak and w > 0:
            out.append(
                f'<text class="valuelabel" x="{label_w + w + 6:.1f}" y="{y + bar_h - 2:.1f}">'
                f"{esc(fmt(value))}</text>"
            )
    out.append("</svg>")
    return "".join(out)


def column_chart(
    counts: list[int],
    bin_width: float,
    x_label: str,
    y_label: str,
    x_min: float = 0.0,
    ref_x: float | None = None,
    ref_label: str = "",
    fmt=None,
    x_ticks: list[float] | None = None,
) -> str:
    """A distribution as columns, linear on both axes.

    `x_min` exists for the log-ratio histogram, whose axis is centred on zero rather
    than starting there. `ref_x` draws one labelled reference line -- the median of a
    ratio, or the no-change point -- because on a signed axis "where is zero" is the
    first thing a reader needs and a gridline cannot say it.
    """
    if not counts:
        return ""
    fmt = fmt or (lambda v: compact(v))
    left, bottom, top, right = 54.0, 36.0, 26.0, 8.0
    plot_w, plot_h = 800.0, 170.0
    total_w, total_h = left + plot_w + right, top + plot_h + bottom
    peak = max(counts) or 1
    ticks = nice_ticks(peak, 3)
    slot = plot_w / len(counts)
    bar_w = max(1.0, slot - 2.0)  # the 2px surface gap between adjacent columns
    x_max = x_min + len(counts) * bin_width

    def to_x(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_w

    out = [
        f'<svg class="chart" viewBox="0 0 {total_w:.0f} {total_h:.0f}" width="100%" '
        f'height="{total_h:.0f}" role="img" preserveAspectRatio="xMinYMid meet">'
    ]
    for t in ticks:
        y = top + plot_h - (t / ticks[-1]) * plot_h
        out.append(
            f'<line x1="{left:.1f}" y1="{y:.1f}" x2="{left + plot_w:.1f}" y2="{y:.1f}" '
            f'stroke="var(--grid)" stroke-width="1"/>'
        )
        out.append(
            f'<text class="tick" x="{left - 8:.0f}" y="{y + 4:.1f}" text-anchor="end">'
            f"{esc(compact(t))}</text>"
        )
    for i, c in enumerate(counts):
        h = (c / ticks[-1]) * plot_h if ticks[-1] else 0.0
        x = left + i * slot + (slot - bar_w) / 2
        lo, hi = x_min + i * bin_width, x_min + (i + 1) * bin_width
        out.append(
            f'<path d="{column_path(x, top + plot_h - h, bar_w, h, radius=2.0)}" '
            f'fill="var(--series)" tabindex="0" '
            f'data-tip="{esc(f"{fmt(lo)} to {fmt(hi)}")}: {esc(thousands(c))}"/>'
        )
    if ref_x is not None and x_min <= ref_x <= x_max:
        rx = to_x(ref_x)
        out.append(
            f'<line x1="{rx:.1f}" y1="{top:.1f}" x2="{rx:.1f}" y2="{top + plot_h:.1f}" '
            f'stroke="var(--ink2)" stroke-width="1"/>'
        )
        if ref_label:
            anchor = "start" if rx < left + plot_w * 0.75 else "end"
            dx = 4 if anchor == "start" else -4
            out.append(
                f'<text class="valuelabel" x="{rx + dx:.1f}" y="{top + 10:.0f}" '
                f'text-anchor="{anchor}">{esc(ref_label)}</text>'
            )
    out.append(
        f'<line x1="{left:.1f}" y1="{top + plot_h:.1f}" x2="{left + plot_w:.1f}" '
        f'y2="{top + plot_h:.1f}" stroke="var(--axis)" stroke-width="1"/>'
    )
    if x_ticks:
        # Explicit ticks, for an axis whose ends are not enough: on a signed log
        # ratio a reader needs every integer, because each one is a doubling.
        for t in x_ticks:
            if not x_min <= t <= x_max:
                continue
            tx = to_x(t)
            out.append(
                f'<line x1="{tx:.1f}" y1="{top + plot_h:.1f}" x2="{tx:.1f}" '
                f'y2="{top + plot_h + 4:.1f}" stroke="var(--axis)" stroke-width="1"/>'
                f'<text class="tick" x="{tx:.1f}" y="{top + plot_h + 16:.0f}" '
                f'text-anchor="middle">{esc(fmt(t))}</text>'
            )
        out.append(
            f'<text class="tick" x="{left + plot_w / 2:.0f}" y="{total_h - 2:.0f}" '
            f'text-anchor="middle">{esc(x_label)}</text>'
        )
    else:
        out.append(
            f'<text class="tick" x="{left:.0f}" y="{total_h - 6:.0f}">{esc(fmt(x_min))}</text>'
            f'<text class="tick" x="{left + plot_w:.0f}" y="{total_h - 6:.0f}" text-anchor="end">'
            f"{esc(fmt(x_max))}</text>"
            f'<text class="tick" x="{left + plot_w / 2:.0f}" y="{total_h - 6:.0f}" '
            f'text-anchor="middle">{esc(x_label)}</text>'
        )
    out.append(f'<text class="axistitle" x="0" y="10">{esc(y_label)}</text>')
    out.append("</svg>")
    return "".join(out)


def dumbbell_chart(rows: list[tuple[str, float, float]], unit: str, fmt) -> str:
    """Before and after per channel, as a connected pair of dots.

    The form for before-and-after on the same measure: the line carries the change
    and its direction, which paired bars make you compute by comparing two lengths.
    One hue in two shades rather than two hues, because these are two states of one
    quantity and not two categories.

    Both dots carry a 2px ring in the surface colour so they stay legible where they
    overlap -- which is exactly what happens on the background channels, whose value
    does not change because they were never subtracted.
    """
    if not rows:
        return ""
    label_w, right_pad, row_h = 96.0, 56.0, 22.0
    axis_band, plot_w = 26.0, 680.0
    height = row_h * len(rows) + axis_band
    total_w = label_w + plot_w + right_pad
    upper = max((max(b, a) for _, b, a in rows), default=0.0)
    ticks = nice_ticks(upper if upper > 0 else 1.0)
    scale = plot_w / (ticks[-1] if ticks[-1] else 1.0)

    out = [
        f'<svg class="chart" viewBox="0 0 {total_w:.0f} {height:.0f}" width="100%" '
        f'height="{height:.0f}" role="img" preserveAspectRatio="xMinYMid meet">'
    ]
    for t in ticks:
        x = label_w + t * scale
        out.append(
            f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{row_h * len(rows):.1f}" '
            f'stroke="var(--grid)" stroke-width="1"/>'
            f'<text class="tick" x="{x:.1f}" y="{row_h * len(rows) + 16:.0f}" '
            f'text-anchor="middle">{esc(fmt(t))}</text>'
        )
    for i, (name, before, after) in enumerate(rows):
        y = i * row_h + row_h / 2
        xb, xa = label_w + before * scale, label_w + after * scale
        out.append(
            f'<text class="rowlabel" x="{label_w - 8:.0f}" y="{y + 4:.1f}" '
            f'text-anchor="end">{esc(name)}</text>'
        )
        out.append(
            f'<line x1="{min(xb, xa):.1f}" y1="{y:.1f}" x2="{max(xb, xa):.1f}" y2="{y:.1f}" '
            f'stroke="var(--wash)" stroke-width="2" stroke-linecap="round"/>'
        )
        tip = f"{name}: {fmt(before)} before, {fmt(after)} after {unit}"
        out.append(
            f'<circle cx="{xb:.1f}" cy="{y:.1f}" r="4.5" fill="var(--wash)" '
            f'stroke="var(--surface)" stroke-width="2" tabindex="0" data-tip="{esc(tip)}"/>'
            f'<circle cx="{xa:.1f}" cy="{y:.1f}" r="4.5" fill="var(--series)" '
            f'stroke="var(--surface)" stroke-width="2" tabindex="0" data-tip="{esc(tip)}"/>'
        )
        out.append(
            f'<text class="valuelabel" x="{max(xb, xa) + 8:.1f}" y="{y + 4:.1f}">{esc(fmt(after))}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def two_key_legend(before_label: str, after_label: str) -> str:
    """Two series means a legend is present, always."""
    return (
        f'<div class="legend">'
        f'<span class="key"><span class="dot" style="background:var(--wash)"></span>'
        f"{esc(before_label)}</span>"
        f'<span class="key"><span class="dot" style="background:var(--series)"></span>'
        f"{esc(after_label)}</span></div>"
    )


def heat_class(value: int, upper: int, n: int = 5) -> int:
    """Which of the five sequential steps a count falls in."""
    if upper <= 0:
        return 0
    return min(n - 1, int(value / upper * n)) if value < upper else n - 1


def patch_heatmap(counts: list[int], ilocs: list[list[int]] | None) -> str:
    """Cells per patch, laid out as the tiling grid.

    Laid out spatially rather than as a bar per patch, because position is the
    whole point: a patch with no cells at the slide's edge is background, and the
    same patch in the middle of tissue is a failure. A list of 72 numbers cannot
    show the difference.

    An empty patch is not the bottom of the magnitude ramp -- it is a finding, so
    it gets the surface, a ring in the critical colour and a visible zero, and it
    is called out in the legend by name.
    """
    if not counts:
        return ""
    if ilocs and len(ilocs) == len(counts):
        cols = max(i[0] for i in ilocs) + 1
        rows_n = max(i[1] for i in ilocs) + 1
        placed = {(i[0], i[1]): c for i, c in zip(ilocs, counts, strict=True)}
    else:
        # No ilocs: fall back to a single row rather than inventing a grid shape.
        cols, rows_n = len(counts), 1
        placed = {(i, 0): c for i, c in enumerate(counts)}

    cell, gap = 44.0, 2.0  # the 2px separation is surface, not a stroke
    width = cols * (cell + gap)
    height = rows_n * (cell + gap)
    upper = max(counts) or 1

    out = [
        f'<svg class="chart" viewBox="0 0 {width:.0f} {height:.0f}" width="100%" '
        f'height="{min(height, 340):.0f}" role="img" preserveAspectRatio="xMinYMin meet">'
    ]
    for (cx, cy), value in sorted(placed.items()):
        x, y = cx * (cell + gap), cy * (cell + gap)
        tip = f"patch ({cx}, {cy}): {thousands(value)} cells"
        if value == 0:
            out.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell:.1f}" height="{cell:.1f}" rx="3" '
                f'fill="var(--surface)" stroke="{STATUS["critical"]}" stroke-width="1.5" '
                f'tabindex="0" data-tip="{esc(tip)} — no cells"/>'
                f'<text class="cellzero" x="{x + cell / 2:.1f}" y="{y + cell / 2 + 4:.1f}" '
                f'text-anchor="middle">0</text>'
            )
            continue
        step = heat_class(value, upper)
        # An inline style, not a fill attribute: the stylesheet's `text { fill: ... }`
        # rule beats a presentation attribute, which made every in-cell number render
        # in the muted axis grey on a saturated blue. The per-step ink is a variable
        # because which end of the ramp is dark differs between the two modes.
        out.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell:.1f}" height="{cell:.1f}" rx="3" '
            f'fill="var(--heat-{step})" tabindex="0" data-tip="{esc(tip)}"/>'
            f'<text class="cellval" x="{x + cell / 2:.1f}" y="{y + cell / 2 + 4:.1f}" '
            f'text-anchor="middle" style="fill:var(--heat-ink-{step})">'
            f"{esc(compact(value))}</text>"
        )
    out.append("</svg>")
    return "".join(out)


def heat_legend(upper: int) -> str:
    """The scale legend the heatmap needs to be readable at all."""
    edges = [round(upper * i / 5) for i in range(6)]
    swatches = "".join(
        f'<span class="key"><span class="sw" style="background:var(--heat-{i})"></span>'
        f"{esc(compact(edges[i]))}&ndash;{esc(compact(edges[i + 1]))}</span>"
        for i in range(5)
    )
    zero = (
        f'<span class="key"><span class="sw" '
        f'style="background:var(--surface);border:1.5px solid {STATUS["critical"]}"></span>'
        f"no cells</span>"
    )
    return f'<div class="legend">{zero}{swatches}</div>'


def status_row(label: str, ok: bool, detail: str) -> str:
    state = "good" if ok else "critical"
    return (
        f'<div class="statusrow"><span class="badge" style="color:{STATUS[state]}">'
        f'{GLYPH[state]}</span><span class="statuslabel">{esc(label)}</span>'
        f'<span class="statusdetail">{esc(detail)}</span></div>'
    )


def tile(label: str, value: str, note: str = "") -> str:
    return (
        f'<div class="tile"><div class="tilelabel">{esc(label)}</div>'
        f'<div class="tileval">{esc(value)}</div>'
        f'<div class="tilenote">{esc(note)}</div></div>'
    )


def table(headers: list[str], rows: list[list[str]], caption: str = "") -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    cap = f"<caption>{esc(caption)}</caption>" if caption else ""
    return f"<table>{cap}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def details(summary: str, content: str) -> str:
    """A chart's table twin, collapsed. Present for every chart, never omitted."""
    return f"<details><summary>{esc(summary)}</summary>{content}</details>"


def css() -> str:
    def block(p: dict[str, Any]) -> str:
        heat = "".join(f"--heat-{i}:{c};" for i, c in enumerate(p["heat"]))
        heat += "".join(f"--heat-ink-{i}:{c};" for i, c in enumerate(p["heat_ink"]))
        heat += "".join(f"--div-{i}:{c};" for i, c in enumerate(p["div"]))
        heat += "".join(f"--div-ink-{i}:{c};" for i, c in enumerate(p["div_ink"]))
        return (
            f"--surface:{p['surface']};--plane:{p['plane']};--ink:{p['ink']};"
            f"--ink2:{p['ink2']};--muted:{p['muted']};--grid:{p['grid']};"
            f"--axis:{p['axis']};--border:{p['border']};--series:{p['series']};"
            f"--wash:{p['wash']};{heat}"
        )

    return f"""
:root {{ color-scheme: light; {block(LIGHT)} }}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{ color-scheme: dark; {block(DARK)} }}
}}
:root[data-theme="dark"] {{ color-scheme: dark; {block(DARK)} }}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 28px 24px 64px; background: var(--plane); color: var(--ink);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}}
.wrap {{ max-width: 1080px; margin: 0 auto; }}
header {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }}
h1 {{ font-size: 20px; margin: 0 0 4px; font-weight: 600; }}
.sub {{ color: var(--ink2); font-size: 13px; }}
.sub code {{ font-size: 12px; color: var(--muted); overflow-wrap: anywhere; }}
button {{
  font: inherit; color: var(--ink2); background: var(--surface);
  border: 1px solid var(--border); border-radius: 6px; padding: 5px 11px; cursor: pointer;
}}
section {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 18px 20px; margin: 16px 0;
}}
h2 {{ font-size: 15px; margin: 0 0 2px; font-weight: 600; }}
.note {{ color: var(--ink2); font-size: 13px; margin: 0 0 14px; }}
.hero {{ font-size: 52px; line-height: 1.05; font-weight: 600; letter-spacing: -0.02em; }}
.herolabel {{ color: var(--ink2); font-size: 13px; }}
.tiles {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }}
.tile {{
  flex: 1 1 132px; border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px;
}}
.tilelabel {{ color: var(--ink2); font-size: 12px; }}
.tileval {{ font-size: 22px; font-weight: 600; margin-top: 2px; }}
.tilenote {{ color: var(--muted); font-size: 11px; min-height: 15px; }}
.statusrow {{ display: flex; align-items: baseline; gap: 8px; padding: 3px 0; }}
.badge {{ font-size: 14px; width: 16px; }}
.statuslabel {{ min-width: 260px; }}
.statusdetail {{ color: var(--ink2); font-size: 13px; overflow-wrap: anywhere; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 8px; }}
caption {{ text-align: left; color: var(--ink2); font-size: 12px; padding-bottom: 6px; }}
th {{
  text-align: right; font-weight: 600; color: var(--ink2); font-size: 12px;
  border-bottom: 1px solid var(--axis); padding: 5px 8px; white-space: nowrap;
}}
th:first-child, td:first-child {{ text-align: left; }}
td {{
  text-align: right; padding: 4px 8px; border-bottom: 1px solid var(--grid);
  font-variant-numeric: tabular-nums; white-space: nowrap;
}}
td.spark {{ padding: 0 8px; text-align: left; white-space: nowrap; }}\n.sparkhi {{ color: var(--muted); font-size: 11px; margin-left: 6px;\n  font-variant-numeric: tabular-nums; }}\n.spark svg {{ vertical-align: middle; }}
.chart {{ display: block; overflow: visible; }}
text {{ font: 11px system-ui, -apple-system, sans-serif; fill: var(--muted); }}
.tick {{ font-variant-numeric: tabular-nums; }}
.rowlabel {{ fill: var(--ink2); }}
.valuelabel {{ fill: var(--ink2); font-variant-numeric: tabular-nums; }}
.axistitle {{ fill: var(--ink2); }}
.cellval, .cellzero {{ font-size: 10px; font-variant-numeric: tabular-nums; }}
.cellzero {{ fill: var(--ink2); font-weight: 600; }}
path[tabindex], rect[tabindex] {{ outline: none; }}
path[tabindex]:focus-visible, rect[tabindex]:focus-visible {{
  stroke: var(--ink); stroke-width: 2;
}}
.legend {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 10px 0 2px; font-size: 12px;
  color: var(--ink2); }}
.key {{ display: inline-flex; align-items: center; gap: 5px; }}
.sw {{ width: 12px; height: 12px; border-radius: 3px; display: inline-block; }}
.dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
.gallery {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 14px; margin-top: 12px; }}
.gallery.small {{ grid-template-columns: repeat(auto-fit, minmax(140px, 160px)); }}
figure {{ margin: 0; }}
figure img {{ width: 100%; height: auto; display: block; border-radius: 6px;
  border: 1px solid var(--border); background: #000; }}
figcaption {{ color: var(--ink2); font-size: 12px; margin-top: 5px; }}
.figsub {{ color: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }}
.snapgroup {{ margin-top: 16px; }}
.snaphead {{ font-size: 13px; font-weight: 600; }}
.muted {{ color: var(--muted); font-weight: 400; }}
details {{ margin-top: 12px; }}
summary {{ cursor: pointer; color: var(--ink2); font-size: 12px; }}
.grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 22px; }}
@media (max-width: 860px) {{ .grid2 {{ grid-template-columns: 1fr; }} }}
#tip {{
  position: fixed; pointer-events: none; opacity: 0; transition: opacity .1s;
  background: var(--ink); color: var(--surface); font-size: 12px; padding: 4px 8px;
  border-radius: 5px; z-index: 10; font-variant-numeric: tabular-nums;
}}
footer {{ color: var(--muted); font-size: 12px; margin-top: 22px; }}
@media print {{ body {{ background: #fff; }} details {{ display: block; }} }}
"""


JS = """
// Hover and keyboard focus show the same tooltip. Nothing is reachable by hover
// alone: every value here is also in the table under each chart.
(function () {
  var tip = document.getElementById('tip');
  function show(el) {
    var t = el.getAttribute('data-tip');
    if (!t) return;
    var b = el.getBoundingClientRect();
    tip.textContent = t;
    tip.style.opacity = 1;
    var left = b.left + b.width / 2 - tip.offsetWidth / 2;
    tip.style.left = Math.max(4, Math.min(left, innerWidth - tip.offsetWidth - 4)) + 'px';
    tip.style.top = Math.max(4, b.top - tip.offsetHeight - 8) + 'px';
  }
  function hide() { tip.style.opacity = 0; }
  ['mouseover', 'focusin'].forEach(function (e) {
    document.addEventListener(e, function (ev) {
      var el = ev.target.closest('[data-tip]');
      if (el) show(el); else hide();
    });
  });
  ['mouseout', 'focusout', 'scroll'].forEach(function (e) {
    document.addEventListener(e, hide, true);
  });
  var btn = document.getElementById('theme');
  btn.addEventListener('click', function () {
    var root = document.documentElement;
    var dark = getComputedStyle(root).colorScheme.indexOf('dark') === 0;
    root.setAttribute('data-theme', dark ? 'light' : 'dark');
  });
})();
"""


def channel_section(channels: dict[str, Any]) -> str:
    per = channels["per_channel"]
    names = list(per)

    headers = [
        "Channel",
        "Min",
        "Max",
        "Intensity distribution (&radic;count), 0 to the value at its right",
        "Mean",
        "Median",
        "p99",
        "p99.99",
        "Zero px",
        "At ceiling",
    ]
    rows = []
    for name in names:
        m = per[name]
        # Each sparkline is binned to its own p99.9, so the axis differs per row.
        # The upper bound is printed beside it rather than left implicit, and min and
        # max give the channel's true extent alongside it.
        upper = m.get("histogram_upper", m["max"])
        rows.append(
            [
                esc(name),
                thousands(m["min"]),
                thousands(m["max"]),
                sparkline(m["histogram"]) + f'<span class="sparkhi">{esc(thousands(upper))}</span>',
                f"{m['mean']:,.1f}",
                thousands(m["p50"]),
                thousands(m["p99"]),
                thousands(m["p99_99"]),
                f"{m['fraction_zero'] * 100:.2f}%",
                f"{m['fraction_at_dtype_ceiling'] * 100:.3f}%",
            ]
        )
    head_row = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join(
        "<tr>"
        + f"<td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td class='spark'>{r[3]}</td>"
        + "".join(f"<td>{c}</td>" for c in r[4:])
        + "</tr>"
        for r in rows
    )
    ceiling = next(iter(per.values()))["dtype_ceiling"]

    # The before-and-after comparison only exists if the pre-subtraction image was
    # given. Without it this stays a single-series chart rather than pretending to a
    # baseline it does not have.
    has_before = all("before" in per[n] for n in names)
    if has_before:
        zero_chart = two_key_legend("before subtraction", "after subtraction") + dumbbell_chart(
            [(n, per[n]["before"]["fraction_zero"] * 100, per[n]["fraction_zero"] * 100) for n in names],
            "of pixels",
            lambda v: f"{v:.1f}%",
        )
        zero_table = table(
            ["Channel", "Before", "After", "Change"],
            [
                [
                    esc(n),
                    f"{per[n]['before']['fraction_zero'] * 100:.2f}%",
                    f"{per[n]['fraction_zero'] * 100:.2f}%",
                    f"{(per[n]['fraction_zero'] - per[n]['before']['fraction_zero']) * 100:+.2f} pp",
                ]
                for n in names
            ],
        )
        zero_note = (
            "Background subtraction clips at zero, so pixels driven to zero are signal it "
            "removed. The pair shows how much each channel moved. Channels used only as "
            "background are never subtracted, so their two dots coincide, which is what a "
            "correct run looks like."
        )
    else:
        zero_chart = hbar_chart(
            [(n, per[n]["fraction_zero"] * 100) for n in names],
            "percent of pixels",
            lambda v: f"{v:.0f}%",
        )
        zero_table = table(
            ["Channel", "Zero px"],
            [[esc(n), f"{per[n]['fraction_zero'] * 100:.2f}%"] for n in names],
        )
        zero_note = (
            "Background subtraction clips at zero, so a high fraction here means signal was "
            "subtracted away. Unsubtracted channels give the baseline. Pass the "
            "pre-subtraction image to compare before and after directly."
        )

    return f"""
<section>
  <h2>Channels</h2>
  <p class="note">Measured on the full-resolution image, every pixel. Percentiles are
  exact rather than interpolated, so each one is a value that genuinely occurs.
  &ldquo;At ceiling&rdquo; is true saturation, at {thousands(ceiling)}.</p>
  <table><thead><tr>{head_row}</tr></thead><tbody>{body}</tbody></table>
</section>

<section>
  <h2>Zero pixels per channel</h2>
  <p class="note">{zero_note}</p>
  {zero_chart}
  {details("Show as table", zero_table)}
</section>
"""


def cycle_ratio_section(ratio: dict[str, Any]) -> str:
    """The cross-cycle nuclear comparison, or why it could not be made.

    Reports the absence explicitly rather than omitting the section. A missing
    section reads as "nothing wrong here", and a single-cycle run or an unmatched
    nuclear pattern is a gap in the QC rather than a clean result.
    """
    if not ratio.get("available"):
        return f"""
<section>
  <h2>Nuclear stain across cycles</h2>
  <p class="note">Not computed: {esc(ratio.get("reason", "unavailable"))}.</p>
</section>
"""
    if "histogram" not in ratio:
        return f"""
<section>
  <h2>Nuclear stain across cycles</h2>
  <p class="note">{esc(ratio.get("note", "no comparable cells"))}.</p>
</section>
"""

    median = ratio["median_log2_ratio"]
    lost = ratio["fraction_below_half"] * 100
    lo, hi = ratio["histogram_min"], ratio["histogram_max"]
    chart = column_chart(
        ratio["histogram"],
        ratio["histogram_bin_width"],
        f"log2({esc(ratio['last_channel'])} / {esc(ratio['first_channel'])})",
        "cells",
        x_min=lo,
        ref_x=0.0,
        ref_label="no change",
        fmt=lambda v: f"{v:+g}",
        x_ticks=[float(t) for t in range(math.ceil(lo), math.floor(hi) + 1)],
    )
    summary = table(
        ["Statistic", "Value"],
        [
            ["First cycle channel", f"{esc(ratio['first_channel'])} (cycle {ratio['first_cycle']})"],
            ["Last cycle channel", f"{esc(ratio['last_channel'])} (cycle {ratio['last_cycle']})"],
            ["Cells compared", thousands(ratio["n_usable"])],
            ["Cells with no signal in one cycle", thousands(ratio["n_undefined"])],
            ["Median log2 ratio", f"{median:+.3f}"],
            ["Mean log2 ratio", f"{ratio['mean_log2_ratio']:+.3f}"],
            ["p1 / p99 log2 ratio", f"{ratio['p1_log2_ratio']:+.2f} / {ratio['p99_log2_ratio']:+.2f}"],
            [
                "Cells at least halved",
                f"{thousands(ratio['n_below_half'])} ({lost:.2f}%)",
            ],
            [
                "Beyond the drawn range",
                f"{thousands(ratio['n_below_histogram_min'])} below, "
                f"{thousands(ratio['n_above_histogram_max'])} above",
            ],
        ],
    )
    return f"""
<section>
  <h2>Nuclear stain across cycles</h2>
  <p class="note">Per cell, the last cycle's nuclear stain over the first cycle's, as
  log2 &mdash; so &minus;1 is half and +1 is double, at equal distance from no change.
  Every cycle re-images a nuclear stain, so the same structure is present in each
  round and a drop is the sample or the optics rather than the biology. A cell that
  detached or sat under tissue lost in a wash keeps its first-cycle signal and loses
  its last, which shows up as a left-hand shoulder. Here the median is
  <strong>{median:+.2f}</strong> and {lost:.2f}% of cells at least halved. Cells with
  no signal in one of the two cycles are excluded and counted, because their ratio is
  undefined rather than large.</p>
  {chart}
  {details("Show as table", summary)}
</section>
"""


def inline_png(path: Path) -> str:
    """A PNG as a data URI.

    The one place this script touches a file other than its JSON, and it does not
    interpret it: bytes in, base64 out. That keeps the rule that rendering cannot
    change a measurement, while still producing one file that opens with no network
    and no sidecar directory to lose.
    """
    import base64

    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def figure(src: str, caption: str, sub: str = "") -> str:
    subline = f'<div class="figsub">{sub}</div>' if sub else ""
    return (
        f'<figure><img src="{src}" alt="{esc(caption)}" loading="lazy">'
        f"<figcaption>{caption}{subline}</figcaption></figure>"
    )


def crops_section(images: dict[str, Any], asset_dir: Path) -> str:
    """The segmentation crops, ordered densest first."""
    crops = images.get("crops") or []
    if not crops:
        return ""
    total = crops[0].get("n_nonempty_windows", 0)
    figs = []
    for c in crops:
        path = asset_dir / c["file"]
        if not path.exists():
            continue
        figs.append(
            figure(
                inline_png(path),
                f"{esc(c['density_band'])} &middot; {thousands(c['n_cells'])} cells",
                f"({c['x0']:,}, {c['y0']:,}) &middot; {c['width']}&times;{c['height']} px "
                f"&middot; rank {c['density_rank']} of {total} "
                f"&middot; {c['n_outlines']} outlines drawn",
            )
        )
    if not figs:
        return ""
    first = crops[0]
    return f"""
<section>
  <h2>Segmentation overlay</h2>
  <p class="note">{first["width"]}&times;{first["height"]} px windows at full
  resolution, showing <strong>{esc(first["channel"])}</strong> in grey with the
  segmentation boundary drawn in
  <span style="color:#00b8cc"><strong>cyan</strong></span>, outline only so the pixels
  under the mask stay visible. Windows are chosen across the density range rather than
  at random, because segmentation fails differently in packed tissue than at a sparse
  edge, and a random sample of a mostly-empty slide is mostly background. All crops
  share one display range, {thousands(first["display_min"])}&ndash;{thousands(first["display_max"])},
  so a dim region looks dim instead of being brightened to match. Outline counts exceed
  cell counts because a cell straddling the frame is still drawn, and a window at the
  image's right or bottom edge is clipped to what exists, so its stated size is smaller
  than the rest.</p>
  <div class="gallery">{"".join(figs)}</div>
</section>
"""


def cluster_heatmap(clustering: dict[str, Any]) -> str:
    """Clusters against markers, z-scored, on a diverging ramp.

    Diverging rather than sequential because the value is a signed deviation from the
    slide's mean for that marker: above and below are opposite things, and the
    midpoint has to read as "average", which only a neutral grey does. A sequential
    ramp would make "average" look like "somewhat high".
    """
    matrix = clustering.get("matrix") or []
    markers = clustering.get("channels_used") or []
    clusters = clustering.get("clusters") or []
    if not matrix or not markers:
        return ""

    peak = max((abs(v) for row in matrix for v in row), default=1.0) or 1.0
    cell_w, cell_h, gap = 66.0, 26.0, 2.0
    # Horizontal marker labels, not rotated. Rotated ones were clipped to their last
    # few characters -- "Vimentin" read as "tin" -- and at eight markers the names fit
    # a 66px column outright, so the rotation bought nothing and cost legibility.
    label_w, top_band = 112.0, 26.0
    width = label_w + len(markers) * (cell_w + gap)
    height = top_band + len(clusters) * (cell_h + gap)

    out = [
        f'<svg class="chart" viewBox="0 0 {width:.0f} {height:.0f}" width="100%" '
        f'height="{height:.0f}" role="img" preserveAspectRatio="xMinYMin meet">'
    ]
    for j, marker in enumerate(markers):
        x = label_w + j * (cell_w + gap) + cell_w / 2
        out.append(
            f'<text class="rowlabel" x="{x:.1f}" y="{top_band - 9:.0f}" '
            f'text-anchor="middle">{esc(marker)}</text>'
        )
    for i, cluster in enumerate(clusters):
        y = top_band + i * (cell_h + gap)
        size = clustering["cluster_sizes"][i]
        out.append(
            f'<text class="rowlabel" x="{label_w - 8:.0f}" y="{y + cell_h / 2 + 4:.1f}" '
            f'text-anchor="end">{esc(cluster)} ({esc(compact(size))})</text>'
        )
        for j, marker in enumerate(markers):
            value = matrix[i][j]
            x = label_w + j * (cell_w + gap)
            step = diverging_step(value, peak)
            out.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell_w:.1f}" height="{cell_h:.1f}" '
                f'rx="3" fill="var(--div-{step})" tabindex="0" '
                f'data-tip="cluster {esc(cluster)} &middot; {esc(marker)}: {value:+.2f}"/>'
                f'<text class="cellval" x="{x + cell_w / 2:.1f}" y="{y + cell_h / 2 + 4:.1f}" '
                f'text-anchor="middle" style="fill:var(--div-ink-{step})">{value:+.1f}</text>'
            )
    out.append("</svg>")
    return "".join(out)


def diverging_step(value: float, peak: float) -> int:
    """Which of seven diverging steps a signed value falls in, 3 being the midpoint."""
    if peak <= 0:
        return 3
    fraction = max(-1.0, min(1.0, value / peak))
    return max(0, min(6, int(round(fraction * 3)) + 3))


def diverging_legend() -> str:
    keys = "".join(
        f'<span class="key"><span class="sw" style="background:var(--div-{i})"></span>'
        f"{['much lower', 'lower', 'slightly lower', 'average', 'slightly higher', 'higher', 'much higher'][i]}"
        f"</span>"
        for i in range(7)
    )
    return f'<div class="legend">{keys}</div>'


def clustering_section(images: dict[str, Any], asset_dir: Path) -> str:
    clustering = images.get("clustering")
    if not clustering:
        return ""
    excluded = clustering.get("excluded_channels") or []

    rows = [
        [
            esc(c),
            thousands(clustering["cluster_sizes"][i]),
            f"{clustering['cluster_sizes'][i] / max(1, clustering['n_cells_clustered']) * 100:.1f}%",
            esc(clustering["top_marker"][i])
            if clustering.get("top_marker_above_average", [True] * 99)[i]
            else "none above average",
        ]
        for i, c in enumerate(clustering["clusters"])
    ]
    subsample_note = (
        f" Clustered on a random {thousands(clustering['n_cells_clustered'])}-cell subsample of "
        f"{thousands(clustering['n_cells_total'])}, because the neighbour graph costs minutes at "
        f"full size and cluster structure does not sharpen past a few tens of thousands."
        if clustering.get("subsampled")
        else ""
    )

    snapshots = images.get("snapshots") or []
    by_cluster: dict[str, list[dict[str, Any]]] = {}
    for s in snapshots:
        by_cluster.setdefault(str(s["cluster"]), []).append(s)

    snap_blocks = []
    for i, cluster in enumerate(clustering["clusters"]):
        figs = []
        for s in by_cluster.get(str(cluster), []):
            path = asset_dir / s["file"]
            if path.exists():
                figs.append(
                    figure(
                        inline_png(path),
                        f"cell {thousands(s['cell_index'])}",
                        f"{s['width']}&times;{s['height']} px",
                    )
                )
        if figs:
            snap_blocks.append(
                f'<div class="snapgroup"><div class="snaphead">Cluster '
                f"{esc(cluster)} &middot; "
                + (
                    f"{esc(clustering['top_marker'][i])}"
                    if clustering.get("top_marker_above_average", [True] * 99)[i]
                    else f"no marker above average, showing {esc(clustering['top_marker'][i])}"
                )
                + f' <span class="muted">({esc(compact(clustering["cluster_sizes"][i]))} cells)'
                f'</span></div><div class="gallery small">{"".join(figs)}</div></div>'
            )

    snap_section = ""
    if snap_blocks:
        snap_section = f"""
<section>
  <h2>Representative cells per cluster</h2>
  <p class="note">Two cells per cluster, each the nearest to its cluster's centre in
  marker space rather than the brightest &mdash; the brightest cell is usually the most
  extreme, which is the opposite of representative. Each is shown in its cluster's own
  top marker (<span style="color:#b5179e"><strong>magenta</strong></span>) &mdash; or,
  where no marker is above the slide average, its least-negative one, said so &mdash; over the
  nuclear stain (<span style="color:#1a7f37"><strong>green</strong></span>), with the
  segmentation boundary in white. If a cluster's cells do not look like its marker
  profile claims, the cluster is an artefact.</p>
  {"".join(snap_blocks)}
</section>
"""

    return f"""
<section>
  <h2>Cell clusters by marker intensity</h2>
  <p class="note">Leiden at resolution {clustering["resolution"]} on arcsinh-transformed
  mean intensities, cofactor {clustering["arcsinh_cofactor"]:g}, then scaled per marker.
  arcsinh rather than log because background subtraction leaves many exact zeros and log
  would need an invented pseudocount. No spatial information is used, so these groups are
  a statement about the staining alone: a run whose markers did not work collapses into
  one undifferentiated cluster, which nothing else in this report would show. Values are
  standard deviations from each marker's slide-wide mean.{subsample_note}
  {
        f"Excluded from clustering: {esc(', '.join(excluded))} &mdash; background channels are an "
        f"instrument reading rather than a phenotype, and nuclear stain is in every cell by "
        f"construction, so neither separates cell types."
        if excluded
        else ""
    }</p>
  {diverging_legend()}
  {cluster_heatmap(clustering)}
  {
        details(
            "Show as table",
            table(["Cluster", "Cells", "Share", "Top marker"], rows),
        )
    }
</section>
{snap_section}
"""


def build(
    metrics: dict[str, Any], images: dict[str, Any] | None = None, asset_dir: Path | None = None
) -> str:
    img = metrics["image"]
    cells = metrics["cells"]
    channels = metrics["channels"]
    patches = metrics.get("patches")
    c, h, w = img["shape_cyx"]

    integrity = [
        status_row(
            "Table and image agree on channel names",
            channels["table_matches_image"],
            "identical" if channels["table_matches_image"] else "they differ, so intensities are ambiguous",
        )
    ]
    if "matches_marker_sheet" in channels:
        integrity.append(
            status_row(
                "Image matches the marker sheet",
                channels["matches_marker_sheet"],
                "identical"
                if channels["matches_marker_sheet"]
                else f"sheet says {', '.join(channels['marker_sheet_names'][:4])}…",
            )
        )
    degenerate_ok = cells["n_below_min_cell_area"] == 0
    integrity.append(
        status_row(
            f"No cells below {compact(cells['min_cell_area'])} px²",
            degenerate_ok,
            "none"
            if degenerate_ok
            else f"{thousands(cells['n_below_min_cell_area'])} cells "
            f"({cells['fraction_below_min_cell_area'] * 100:.3f}%), smallest {cells['min']:.1f} px²",
        )
    )
    if patches:
        empty_ok = patches["n_empty_patches"] == 0
        integrity.append(
            status_row(
                "Every patch produced cells",
                empty_ok,
                "all "
                + thousands(patches["n_patches"])
                + " patches"
                + ("" if empty_ok else f"; {patches['n_empty_patches']} empty"),
            )
        )

    tiles = [
        tile("Channels", str(channels["n_channels"]), f"{img['dtype']}, {img['n_pyramid_levels']} levels"),
        tile("Image", f"{w:,} × {h:,}", f"{w * h / 1e6:,.0f} megapixels per channel"),
        tile(
            "Median cell area",
            f"{cells['p50']:,.0f} px²",
            f"p1 {cells['p1']:,.0f} · p99 {cells['p99']:,.0f}",
        ),
        tile(
            "Below min area",
            thousands(cells["n_below_min_cell_area"]),
            f"under {compact(cells['min_cell_area'])} px²",
        ),
    ]
    if patches:
        tiles.append(
            tile(
                "Patches",
                thousands(patches["n_patches"]),
                f"{patches['n_empty_patches']} with no cells",
            )
        )

    area_chart = column_chart(
        cells["histogram"],
        cells["histogram_bin_width"],
        "cell area (px²)",
        "cells",
    )
    area_note = (
        f"Binned to p99 ({cells['histogram_upper']:,.0f} px&sup2;). "
        f"{thousands(cells['n_above_histogram_upper'])} cells fall above that and are not drawn; "
        f"the largest is {cells['max']:,.0f} px&sup2;."
    )
    area_table = table(
        ["Statistic", "px²"],
        [
            ["Minimum", f"{cells['min']:,.1f}"],
            ["p1", f"{cells['p1']:,.0f}"],
            ["p25", f"{cells['p25']:,.0f}"],
            ["Median", f"{cells['p50']:,.0f}"],
            ["p75", f"{cells['p75']:,.0f}"],
            ["p99", f"{cells['p99']:,.0f}"],
            ["p99.9", f"{cells['p99_9']:,.0f}"],
            ["Maximum", f"{cells['max']:,.0f}"],
            ["Mean", f"{cells['mean']:,.0f}"],
        ],
    )

    patch_block = ""
    if patches and patches.get("cells_per_patch"):
        counts = patches["cells_per_patch"]
        ilocs = patches.get("ilocs")
        rows = []
        for i, n in enumerate(counts):
            pos = f"({ilocs[i][0]}, {ilocs[i][1]})" if ilocs else str(i)
            rows.append([pos, thousands(n)])
        patch_block = f"""
<section>
  <h2>Cells per patch</h2>
  <p class="note">Laid out as the tiling grid, so an empty patch can be read against
  its neighbours: at the slide's edge that is background, in the middle of tissue it
  is a failure. Patches overlap by design, so the counts sum to
  {thousands(patches["centroid_assignments"])} against
  {thousands(patches["n_cells"])} cells &mdash; a cell in an overlap is counted by both
  patches it lands in.</p>
  {heat_legend(max(counts))}
  {patch_heatmap(counts, ilocs)}
  {details("Show as table", table(["Patch (x, y)", "Cells"], rows))}
</section>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QC report &middot; {esc(metrics["sample"])}</title>
<style>{css()}</style>
</head>
<body>
<div id="tip" role="status" aria-live="polite"></div>
<div class="wrap">
<header>
  <div>
    <h1>QC report &middot; {esc(metrics["sample"])}</h1>
    <div class="sub">Image element <strong>{esc(metrics["image_element"])}</strong>,
      {c} channels, {w:,} &times; {h:,} px<br>
      <code>{esc(metrics["store"])}</code></div>
  </div>
  <button id="theme" type="button">Toggle theme</button>
</header>

<section>
  <div class="herolabel">Cells segmented</div>
  <div class="hero">{esc(thousands(cells["n_cells"]))}</div>
  <div class="tiles">{"".join(tiles)}</div>
</section>

<section>
  <h2>Integrity checks</h2>
  <p class="note">Observations, not a verdict. This report sets no thresholds and
  returns no exit code: the numbers that would justify a threshold need more than
  one dataset behind them.</p>
  {"".join(integrity)}
</section>

{channel_section(channels)}

{cycle_ratio_section(metrics["cycle_ratio"]) if metrics.get("cycle_ratio") else ""}

<section>
  <h2>Cell area distribution</h2>
  <p class="note">{area_note}</p>
  {area_chart}
  {details("Show as table", area_table)}
</section>

{patch_block}

{crops_section(images, asset_dir) if images and asset_dir else ""}

{clustering_section(images, asset_dir) if images and asset_dir else ""}

<footer>Rendered by <code>bin/qc_report.py</code> from
<code>{esc(metrics["sample"])}</code> metrics. Self-contained: no external scripts,
fonts or network access.</footer>
</div>
<script>{JS}</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--metrics", required=True, type=Path, help="qc metrics JSON")
    ap.add_argument("--out", required=True, type=Path, help="HTML file to write")
    ap.add_argument(
        "--images",
        type=Path,
        help="qc_images.json from qc_images.py. Its PNGs are read from the same directory "
        "and inlined as base64, so the output stays a single self-contained file.",
    )
    args = ap.parse_args()

    metrics = json.loads(args.metrics.read_text())
    images = json.loads(args.images.read_text()) if args.images else None
    asset_dir = args.images.parent if args.images else None
    page = build(metrics, images, asset_dir)
    args.out.write_text(page)

    print(f"[qc_report] {args.out} ({len(page.encode()) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
