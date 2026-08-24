#!/usr/bin/env python3
"""One HTML summary for a dearrayed slide, from the per-core QC metrics.

A TMA run produces one report per core, which answers "is this core sound" N times
and never answers "is this slide sound". Four cores mean four pages to open and a
cross-core comparison a reader has to do in their head, which is exactly where a
core that stained differently hides: each of its own numbers looks unremarkable
until it sits next to the other three.

So this reports the slide, and deliberately not the cores. Anything a reader can
only act on by looking at one core -- crops, clusters, the per-channel histograms,
the patch heatmap -- stays in that core's own report and is linked, not repeated.
What is here is either a slide-level fact, or a per-core number worth comparing
across cores. Cell count is both, which is why it leads.

Reads the same `{core}_qc.json` files QC_METRICS already writes, so it measures
nothing itself and cannot disagree with the core reports. Imports the rendering
primitives from qc_report.py for the same reason: one stylesheet, one table, one
status row, so a slide page and a core page are visibly the same artefact.

Sets no thresholds and returns no exit code, which is the standing rule for QC here
until there are enough slides behind a number to justify one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qc_report import (  # noqa: E402
    JS,
    compact,
    css,
    details,
    esc,
    hbar_chart,
    status_row,
    table,
    thousands,
    tile,
)


def core_label(metrics: dict[str, Any]) -> str:
    """The core's own name, as its report and its merged elements use it."""
    return str(metrics.get("sample") or metrics.get("image_element") or "unknown")


def read_cores(paths: list[Path]) -> list[dict[str, Any]]:
    """Every core's metrics, ordered by core name.

    Sorted rather than left in the order Nextflow staged them: a channel's order is
    not guaranteed, and a table whose rows move between runs cannot be diffed.
    """
    cores = []
    for p in paths:
        d = json.loads(p.read_text())
        # A stub run writes {"sample": ..., "stub": true} and nothing else. Skipped
        # rather than crashed on, so -stub exercises this module's wiring.
        if d.get("stub"):
            continue
        cores.append(d)
    if not cores:
        raise ValueError(
            f"none of the {len(paths)} metrics file(s) carried real measurements. "
            "A stub run produces stub JSON, which has no numbers to summarise."
        )
    cores.sort(key=core_label)
    return cores


def slide_totals(cores: list[dict[str, Any]]) -> dict[str, Any]:
    """The numbers that are only true of the whole slide."""
    n_cells = sum(c["cells"]["n_cells"] for c in cores)
    degenerate = sum(c["cells"]["n_below_min_cell_area"] for c in cores)
    patched = [c for c in cores if c.get("patches")]
    return {
        "n_cores": len(cores),
        "n_cells": n_cells,
        "n_below_min_cell_area": degenerate,
        "fraction_below_min_cell_area": degenerate / n_cells if n_cells else 0.0,
        "n_patches": sum(c["patches"]["n_patches"] for c in patched),
        "n_empty_patches": sum(c["patches"]["n_empty_patches"] for c in patched),
        "median_cells_per_core": sorted(c["cells"]["n_cells"] for c in cores)[len(cores) // 2],
    }


def channel_sets(cores: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Each distinct channel list on the slide, mapped to the cores that have it.

    A slide-level check with no per-core equivalent: every core is a cut of one
    image, so they must all carry the same channels in the same order. If they do
    not, the merged store's tables cannot be compared column for column and the
    per-core reports have no way to notice, because each one only ever sees itself.
    """
    out: dict[str, list[str]] = {}
    for c in cores:
        key = " | ".join(c["channels"]["table_names"])
        out.setdefault(key, []).append(core_label(c))
    return out


def rollup(cores: list[dict[str, Any]], label: str, ok, detail_ok: str) -> str:
    """One integrity row for the slide, from the same check on every core.

    Passes only when every core passes, and names the cores that did not. A slide
    is not partly sound: one core disagreeing about channel names is a fact about
    the slide, and rolling it up to "3 of 4" would be the wrong summary of it.
    """
    failed = [core_label(c) for c in cores if not ok(c)]
    return status_row(
        label,
        not failed,
        detail_ok
        if not failed
        else f"{len(failed)} of {len(cores)}: {', '.join(failed[:4])}" + ("…" if len(failed) > 4 else ""),
    )


def integrity_section(cores: list[dict[str, Any]], totals: dict[str, Any]) -> str:
    rows = [
        rollup(
            cores,
            "Every core's table and image agree on channel names",
            lambda c: c["channels"]["table_matches_image"],
            f"all {len(cores)} cores",
        )
    ]

    sets = channel_sets(cores)
    rows.append(
        status_row(
            "Every core carries the same channels",
            len(sets) == 1,
            f"{len(next(iter(sets)).split(' | '))} channels, identical across cores"
            if len(sets) == 1
            else f"{len(sets)} different channel lists: "
            + "; ".join(f"[{', '.join(v)}]" for v in sets.values()),
        )
    )

    if any("matches_marker_sheet" in c["channels"] for c in cores):
        rows.append(
            rollup(
                cores,
                "Every core matches the marker sheet",
                lambda c: c["channels"].get("matches_marker_sheet", True),
                f"all {len(cores)} cores",
            )
        )

    if any("roles" in c["channels"] for c in cores):
        rows.append(
            rollup(
                cores,
                "Every core declares a nuclear stain",
                lambda c: bool((c["channels"].get("roles") or {}).get("dna")),
                f"all {len(cores)} cores",
            )
        )
        rows.append(
            rollup(
                cores,
                "Every channel has a channel_role",
                lambda c: not c["channels"].get("channels_without_role"),
                f"all {len(cores)} cores",
            )
        )

    if any(c.get("cycle_ratio") for c in cores):
        rows.append(
            rollup(
                cores,
                "The cross-cycle nuclear check ran on every core",
                lambda c: bool((c.get("cycle_ratio") or {}).get("available")),
                f"all {len(cores)} cores",
            )
        )

    if any(c.get("patches") for c in cores):
        rows.append(
            status_row(
                "Every patch on the slide produced cells",
                totals["n_empty_patches"] == 0,
                f"all {totals['n_patches']} patches"
                if totals["n_empty_patches"] == 0
                else f"{totals['n_empty_patches']} of {totals['n_patches']} empty",
            )
        )

    degenerate_ok = totals["n_below_min_cell_area"] == 0
    rows.append(
        status_row(
            "No degenerate cells anywhere on the slide",
            degenerate_ok,
            "none"
            if degenerate_ok
            else f"{thousands(totals['n_below_min_cell_area'])} cells "
            f"({totals['fraction_below_min_cell_area'] * 100:.3f}% of the slide)",
        )
    )
    return "".join(rows)


def cores_section(cores: list[dict[str, Any]], totals: dict[str, Any]) -> str:
    """Cell count per core, which is the one per-core number a slide view needs.

    A core that yielded a fraction of its neighbours either lost tissue or failed
    segmentation, and neither is visible from inside that core's own report, where
    its count is just a number with nothing to be small against.
    """
    chart = hbar_chart(
        [(core_label(c), float(c["cells"]["n_cells"])) for c in cores],
        "cells",
        lambda v: thousands(v),
    )
    rows = []
    for c in cores:
        cells = c["cells"]
        patches = c.get("patches")
        share = cells["n_cells"] / totals["n_cells"] * 100 if totals["n_cells"] else 0.0
        _, h, w = c["image"]["shape_cyx"]
        rows.append(
            [
                esc(core_label(c)),
                thousands(cells["n_cells"]),
                f"{share:.1f}%",
                f"{w:,} × {h:,}",
                thousands(cells["n_below_min_cell_area"]),
                f"{patches['n_patches']} ({patches['n_empty_patches']} empty)" if patches else "not tiled",
            ]
        )
    return f"""
<section>
  <h2>Cells per core</h2>
  <p class="note">The slide holds {esc(thousands(totals["n_cells"]))} cells across
  {totals["n_cores"]} cores, a median of {esc(thousands(totals["median_cells_per_core"]))} each.
  A core well below its neighbours either lost tissue or failed segmentation; neither is
  visible from inside that core's own report, where the count has nothing to be small
  against. Each core's full report, with its crops and clusters, sits beside this file.</p>
  {chart}
  {
        details(
            "Show as table",
            table(
                ["Core", "Cells", "Share of slide", "Image", "Below min area", "Patches"],
                rows,
            ),
        )
    }
</section>
"""


def channel_comparison_section(cores: list[dict[str, Any]]) -> str:
    """Mean intensity per channel, one column per core.

    The comparison the per-core reports structurally cannot make. Each core's page
    shows its own channel against its own histogram, which says whether the channel
    has signal but not whether it has the same signal as the rest of the slide --
    and staining that failed on one core is a per-core failure with a slide-level
    cause, so it is only diagnosable side by side.

    The spread column is max over min, reported and not judged. A ratio near 1 means
    the cores agree; a large one means they do not, and which of those is expected
    depends on the biology of the array, which this file has no way to know.
    """
    names = cores[0]["channels"]["table_names"]
    # Only channels every core has. A slide whose cores disagree about channels has
    # already failed the integrity check above; this section still renders, over the
    # intersection, rather than raising on top of a failure already reported.
    shared = [n for n in names if all(n in c["channels"]["per_channel"] for c in cores)]
    if not shared:
        return ""

    first = cores[0]["channels"]["per_channel"]
    rows = []
    for n in shared:
        means = [c["channels"]["per_channel"][n]["mean"] for c in cores]
        lo, hi = min(means), max(means)
        spread = hi / lo if lo > 0 else float("inf")
        rows.append(
            [
                esc(n),
                esc(first[n].get("role", "—")),
                *[f"{m:,.0f}" for m in means],
                "—" if spread == float("inf") else f"{spread:.1f}×",
            ]
        )

    headers = ["Channel", "Role", *[esc(core_label(c)) for c in cores], "Spread"]
    dropped = [n for n in names if n not in shared]
    note = (
        f" {len(dropped)} channel(s) absent from at least one core are left out: "
        f"{', '.join(esc(d) for d in dropped[:6])}."
        if dropped
        else ""
    )
    return f"""
<section>
  <h2>Channels across cores</h2>
  <p class="note">Mean intensity per channel, one column per core &mdash; the comparison a
  single core's report cannot make. Its own page shows a channel against its own
  histogram, which says whether that channel has signal, not whether it has the same
  signal as the rest of the slide. Staining that failed on one core is a per-core
  failure with a slide-level cause, and only shows up side by side. Spread is the
  largest core mean over the smallest: near 1× the cores agree, and how much
  disagreement is expected depends on what is on the array, which this file cannot
  know.{note}</p>
  {table(headers, rows)}
</section>
"""


def cycle_section(cores: list[dict[str, Any]]) -> str:
    """The cross-cycle nuclear ratio, per core, on one axis.

    Photobleaching is a property of the acquisition rather than of one core, so the
    four numbers should agree. One core drifting away from the others points at that
    core; all four drifting together points at the run.
    """
    have = [c for c in cores if (c.get("cycle_ratio") or {}).get("available")]
    if not have:
        return ""
    first = have[0]["cycle_ratio"]
    rows = [
        [
            esc(core_label(c)),
            f"{c['cycle_ratio']['median_log2_ratio']:+.3f}",
            f"{c['cycle_ratio']['fraction_below_half'] * 100:.2f}%",
            thousands(c["cycle_ratio"]["n_usable"]),
        ]
        for c in have
    ]
    return f"""
<section>
  <h2>Nuclear stain across cycles</h2>
  <p class="note">Per cell, the last cycle's nuclear stain over the first cycle's, as log2,
  summarised per core: &minus;1 is half. Comparing
  <strong>{esc(first["first_channel"])}</strong> with
  <strong>{esc(first["last_channel"])}</strong>, identified by
  {esc(first.get("nuclear_selected_by", "the marker sheet"))}. Photobleaching belongs to
  the acquisition rather than to one core, so these should agree: one core drifting
  away points at that core, all of them drifting together points at the run.</p>
  {table(["Core", "Median log2 ratio", "Cells at least halved", "Cells compared"], rows)}
</section>
"""


def backsub_section(cores: list[dict[str, Any]]) -> str:
    """How far each channel moved under background subtraction, per core.

    Only renders when the pre-subtraction image reached QC, which on this path means
    COREOGRAPH ran before BACKSUB so each core kept an unsubtracted twin of its own
    shape. A channel driven almost entirely to zero has been subtracted away rather
    than corrected, and seeing that on every core at once is what separates a wrong
    exposure in the marker sheet from one bad core.
    """
    have = [c for c in cores if "before" in c]
    if not have:
        return ""
    names = [
        n
        for n in have[0]["channels"]["table_names"]
        if all("before" in c["channels"]["per_channel"].get(n, {}) for c in have)
    ]
    if not names:
        return ""
    rows = []
    for n in names:
        per_core = []
        for c in have:
            m = c["channels"]["per_channel"][n]
            per_core.append(f"{m['before']['fraction_zero'] * 100:.1f}% → {m['fraction_zero'] * 100:.1f}%")
        rows.append([esc(n), esc(have[0]["channels"]["per_channel"][n].get("role", "—")), *per_core])
    return f"""
<section>
  <h2>Background subtraction, before and after</h2>
  <p class="note">Zero-valued pixels before and after subtraction, per channel per core.
  Subtraction clips at zero, so pixels driven to zero are signal it removed. A channel
  used only as background is never subtracted and should not move at all. A channel
  driven almost entirely to zero has been subtracted away rather than corrected &mdash;
  and seeing that on every core at once is what separates a wrong exposure in the marker
  sheet from one bad core.</p>
  {table(["Channel", "Role", *[esc(core_label(c)) for c in have]], rows)}
</section>
"""


def build(slide: str, cores: list[dict[str, Any]]) -> str:
    totals = slide_totals(cores)
    tiles = [
        tile("Cores", str(totals["n_cores"]), "merged into one store"),
        tile("Median per core", compact(totals["median_cells_per_core"]), "cells"),
        tile("Channels", str(cores[0]["channels"]["n_channels"]), "per core"),
        tile(
            "Patches",
            str(totals["n_patches"]),
            f"{totals['n_empty_patches']} with no cells" if totals["n_patches"] else "not tiled",
        ),
    ]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Slide QC &middot; {esc(slide)}</title>
<style>{css()}</style>
</head>
<body>
<div id="tip" role="status" aria-live="polite"></div>
<div id="lightbox" role="dialog" aria-label="Enlarged image">
  <button id="lbclose" type="button" aria-label="Close">&times;</button>
  <img alt=""><figcaption></figcaption>
</div>
<div class="wrap">
<header>
  <div>
    <h1>Slide QC &middot; {esc(slide)}</h1>
    <div class="sub">{totals["n_cores"]} cores, dearrayed and processed independently,
      merged into one store<br>
      <code>{esc(slide)}_merged.zarr</code></div>
  </div>
  <button id="theme" type="button">Toggle theme</button>
</header>

<section>
  <div class="herolabel">Cells on the slide</div>
  <div class="hero">{esc(thousands(totals["n_cells"]))}</div>
  <div class="tiles">{"".join(tiles)}</div>
</section>

<section>
  <h2>Integrity checks</h2>
  <p class="note">Rolled up across every core: a check passes only when all of them pass,
  and the cores that did not are named. A slide is not partly sound &mdash; one core
  disagreeing about its channels is a fact about the slide. Observations, not a verdict:
  this report sets no thresholds and returns no exit code.</p>
  {integrity_section(cores, totals)}
</section>

{cores_section(cores, totals)}

{channel_comparison_section(cores)}

{cycle_section(cores)}

{backsub_section(cores)}

<footer>Rendered by <code>bin/merge_report.py</code> from {totals["n_cores"]} per-core
metrics files. Core-specific detail &mdash; segmentation crops, clusters, per-channel
histograms, patch layout &mdash; stays in each core's own report rather than being
repeated here. Self-contained: no external scripts, fonts or network access.</footer>
</div>
<script>{JS}</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--metrics",
        required=True,
        nargs="+",
        type=Path,
        help="every core's qc metrics JSON, as written by qc_metrics.py",
    )
    ap.add_argument("--out", required=True, type=Path, help="HTML file to write")
    ap.add_argument("--slide", required=True, help="slide name, used in the title")
    args = ap.parse_args()

    cores = read_cores(args.metrics)
    args.out.write_text(build(args.slide, cores))

    totals = slide_totals(cores)
    print(f"[merge_report] {args.slide}: {totals['n_cores']} cores, {totals['n_cells']:,} cells")
    print(f"  written    : {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
