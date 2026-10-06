#!/usr/bin/env python3
"""Compute QC metrics for one sample's SpatialData store and write them as JSON.

Reads the store with zarr directly (no spatialdata import). Optional inputs: marker
sheet, pre-subtraction OME-TIFF. Reports numbers only; it never decides pass or fail.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

# p99.9 and p99.99 catch clipping in the extreme tail long before it moves p99.
PERCENTILES = (1.0, 25.0, 50.0, 75.0, 99.0, 99.9, 99.99)


def percentiles_from_histogram(hist: Any, percentiles: tuple[float, ...] = PERCENTILES) -> dict[str, float]:
    """Exact percentiles from a full-range histogram where `hist[v]` counts pixels of value `v`.

    Uses the "lower" convention, so every reported value occurs in the image.
    """
    import numpy as np

    hist = np.asarray(hist)
    total = int(hist.sum())
    if total == 0:
        raise ValueError("cannot take percentiles of an empty histogram")

    cumulative = np.cumsum(hist)
    out = {}
    for p in percentiles:
        target = p / 100.0 * total
        out[_pct_key(p)] = float(np.searchsorted(cumulative, target, side="left"))
    return out


def _pct_key(p: float) -> str:
    """`99.9` -> `p99_9`, `50.0` -> `p50`. Stable JSON keys for float percentiles."""
    text = f"{p:g}".replace(".", "_")
    return f"p{text}"


def effective_bit_depth(max_value: int) -> int:
    """Bits actually used by the data, rounded up, floored at 8 (0 for an empty channel).

    Real channel maxima were 920 to 13572 in uint16, so a ceiling check alone reads 0.
    """
    if max_value < 0:
        raise ValueError(f"max_value must be non-negative, got {max_value}")
    if max_value == 0:
        return 0
    return max(8, math.ceil(math.log2(max_value + 1)))


def rebin(hist: Any, n_bins: int, upper: int) -> tuple[list[int], float]:
    """Reduce a full-range histogram to `n_bins` counts over `[0, upper]`, for drawing only.

    Returns the counts and the bin width in intensity units.
    """
    import numpy as np

    hist = np.asarray(hist)
    if n_bins < 1:
        raise ValueError(f"n_bins must be at least 1, got {n_bins}")
    if upper < 0:
        raise ValueError(f"upper must be non-negative, got {upper}")

    width = (upper + 1) / n_bins
    counts = np.zeros(n_bins, dtype=np.int64)
    edges = np.minimum((np.arange(n_bins) * width).astype(np.int64), len(hist) - 1)
    summed = np.add.reduceat(hist[: min(len(hist), int(upper) + 1)], edges[edges <= upper])
    counts[: len(summed)] = summed
    return [int(c) for c in counts], float(width)


def channel_metrics(
    hist: Any, dtype_max: int, n_bins: int = 512, histogram_upper: int | None = None
) -> dict[str, Any]:
    """Per-channel intensity metrics from one channel's full-range histogram.

    `fraction_zero` matters because background subtraction clips at zero.
    `histogram_upper` defaults to `dtype_max`.
    """
    import numpy as np

    hist = np.asarray(hist)
    total = int(hist.sum())
    if total == 0:
        raise ValueError("channel has no pixels")

    nonzero_values = np.nonzero(hist)[0]
    max_value = int(nonzero_values[-1])
    min_value = int(nonzero_values[0])

    values = np.arange(len(hist), dtype=np.float64)
    mean = float((values * hist).sum() / total)

    bits = effective_bit_depth(max_value)
    metrics = {
        "min": min_value,
        "max": max_value,
        "mean": mean,
        "n_pixels": total,
        "dtype_ceiling": dtype_max,
        "fraction_at_dtype_ceiling": float(hist[dtype_max] / total) if dtype_max < len(hist) else 0.0,
        "fraction_zero": float(hist[0] / total),
        "effective_bit_depth": bits,
        "headroom_stops": round(math.log2((dtype_max + 1) / (max_value + 1)), 2) if max_value else None,
    }
    metrics.update(percentiles_from_histogram(hist))
    # The caller passes one bound shared by all channels so the drawings are comparable.
    upper = dtype_max if histogram_upper is None else histogram_upper
    counts, width = rebin(hist, n_bins, upper)
    metrics["histogram"] = counts
    metrics["histogram_upper"] = upper
    metrics["histogram_bin_width"] = width
    return metrics


def area_metrics(areas: Any, min_cell_area: float) -> dict[str, Any]:
    """Cell area distribution (square pixels) and the count below `min_cell_area`."""
    import numpy as np

    areas = np.asarray(areas, dtype=np.float64)
    if areas.size == 0:
        raise ValueError("no cells, so no area distribution")

    degenerate = int((areas < min_cell_area).sum())
    out = {
        "n_cells": int(areas.size),
        "min": float(areas.min()),
        "max": float(areas.max()),
        "mean": float(areas.mean()),
        "min_cell_area": min_cell_area,
        "n_below_min_cell_area": degenerate,
        "fraction_below_min_cell_area": degenerate / areas.size,
    }
    for p in PERCENTILES:
        out[_pct_key(p)] = float(np.percentile(areas, p))

    # Binned to p99: area is heavy-tailed (a 12688 px2 outlier against a 1009 median).
    upper = out[_pct_key(99.0)]
    counts, edges = np.histogram(areas, bins=48, range=(0.0, upper))
    out["histogram"] = [int(c) for c in counts]
    out["histogram_upper"] = float(upper)
    out["histogram_bin_width"] = float(edges[1] - edges[0])
    out["n_above_histogram_upper"] = int((areas > upper).sum())
    return out


def cells_per_patch(centroids: Any, bboxes: Any) -> Any:
    """Count cell centroids `(n, 2)` inside each patch bbox `(n, 4)` as x0, y0, x1, y1.

    Patches overlap, so the counts can sum to more than the cell total.
    """
    import numpy as np

    centroids = np.asarray(centroids, dtype=np.float64)
    bboxes = np.asarray(bboxes, dtype=np.float64)
    if centroids.ndim != 2 or centroids.shape[1] != 2:
        raise ValueError(f"centroids must be (n, 2), got {centroids.shape}")
    if bboxes.ndim != 2 or bboxes.shape[1] != 4:
        raise ValueError(f"bboxes must be (n, 4) as x0, y0, x1, y1, got {bboxes.shape}")

    x, y = centroids[:, 0], centroids[:, 1]
    counts = np.empty(len(bboxes), dtype=np.int64)
    for i, (x0, y0, x1, y1) in enumerate(bboxes):
        # Half-open so a centroid on a shared edge is not counted twice.
        counts[i] = int(((x >= x0) & (x < x1) & (y >= y0) & (y < y1)).sum())
    return counts


def patch_metrics(counts: Any, n_cells: int) -> dict[str, Any]:
    """Aggregate the per-patch cell counts into reportable numbers."""
    import numpy as np

    counts = np.asarray(counts)
    if counts.size == 0:
        return {"n_patches": 0}

    empty = int((counts == 0).sum())
    return {
        "n_patches": int(counts.size),
        "n_empty_patches": empty,
        "fraction_empty_patches": empty / counts.size,
        "cells_per_patch_min": int(counts.min()),
        "cells_per_patch_max": int(counts.max()),
        "cells_per_patch_mean": float(counts.mean()),
        "cells_per_patch_median": float(np.median(counts)),
        # Exceeds n_cells because patches overlap.
        "centroid_assignments": int(counts.sum()),
        "n_cells": n_cells,
    }


# Reading the store.


def read_column(node: Any) -> Any:
    """Read one AnnData obs/var column as a plain array, dispatching on `encoding-type`."""
    import numpy as np
    import zarr

    if isinstance(node, zarr.Array):
        return node[:]

    encoding = node.attrs.get("encoding-type")
    if encoding == "categorical":
        categories = np.asarray(node["categories"][:])
        codes = np.asarray(node["codes"][:])
        return categories[codes]
    if encoding in ("nullable-string-array", "nullable-integer", "nullable-boolean"):
        return np.asarray(node["values"][:])
    raise ValueError(
        f"unsupported AnnData column encoding {encoding!r} with keys {sorted(node.keys())}. "
        f"This script needs updating for it."
    )


def image_channel_labels(sdata_path: Path, element: str) -> list[str]:
    """Channel names on the image element, from `omero.channels[].label`."""
    meta = sdata_path / "images" / element / "zarr.json"
    if not meta.exists():
        raise FileNotFoundError(f"{meta} does not exist, so '{element}' is not an image element")
    attrs = json.loads(meta.read_text()).get("attributes", {})
    channels = attrs.get("ome", {}).get("omero", {}).get("channels")
    if channels is None:
        raise ValueError(f"{meta} has no attributes.ome.omero.channels; the store layout has changed")
    return [c["label"] for c in channels]


def channel_histograms(array: Any, band_rows: int = 2048) -> tuple[list[Any], int]:
    """Exact per-channel histograms of a `(c, y, x)` unsigned image, streamed in row bands.

    Must be full resolution: downsampling hides clipped pixels. A 7.4 GB image took
    about 6 seconds. Returns the histograms and the dtype's maximum value.
    """
    import numpy as np

    if array.ndim != 3:
        raise ValueError(f"expected a (c, y, x) image, got shape {array.shape}")

    info = np.iinfo(array.dtype)
    if info.min < 0:
        raise ValueError(f"image dtype {array.dtype} is signed; exact histograms assume unsigned integers")
    n_bins = int(info.max) + 1

    n_channels, height, _ = array.shape
    hists = [np.zeros(n_bins, dtype=np.int64) for _ in range(n_channels)]
    for c in range(n_channels):
        for y0 in range(0, height, band_rows):
            band = array[c, y0 : min(y0 + band_rows, height), :]
            hists[c] += np.bincount(band.ravel(), minlength=n_bins)
    return hists, int(info.max)


# Nuclear-stain fallback for marker sheets without `channel_role`.
DEFAULT_NUCLEAR_PATTERN = "DAPI"


def read_marker_cycles(path: Path) -> list[dict[str, Any]]:
    """Marker sheet rows with cycle, role, compartment and background, in channel order.

    Role and compartment are optional so sheets predating `channel_role` still parse.
    """
    import csv

    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"{path} has no rows")
    for col in ("channel_number", "cycle_number", "marker_name"):
        if col not in rows[0]:
            raise ValueError(f"{path} has no '{col}' column. Columns present: {sorted(rows[0])}")

    out = []
    for r in rows:
        out.append(
            {
                "channel_number": int(r["channel_number"]),
                "cycle_number": int(r["cycle_number"]),
                "marker_name": r["marker_name"].strip(),
                # None, not "", so "the sheet does not say" stays distinguishable.
                "channel_role": (r.get("channel_role") or "").strip().lower() or None,
                "channel_compartment": (r.get("channel_compartment") or "").strip().lower() or None,
                # Not lowercased: channel names are matched exactly.
                "background": (r.get("background") or "").strip() or None,
            }
        )
    out.sort(key=lambda r: r["channel_number"])
    return out


def channels_with_role(rows: list[dict[str, Any]], *roles: str) -> list[str]:
    """Marker names whose `channel_role` is one of `roles`, in channel order."""
    wanted = {r.lower() for r in roles}
    return [r["marker_name"] for r in rows if r.get("channel_role") in wanted]


def compartments_by_channel(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Marker name to `channel_compartment`, for the channels that declare one."""
    return {r["marker_name"]: r["channel_compartment"] for r in rows if r.get("channel_compartment")}


def resolve_nuclear_rows(
    rows: list[dict[str, Any]], pattern: str | None = None
) -> tuple[list[dict[str, Any]], str]:
    """The nuclear-stain rows and a label for how they were identified.

    Precedence: explicit `pattern`, then `channel_role == "dna"` if any row has a role
    (empty if none is dna, no fallback), then DEFAULT_NUCLEAR_PATTERN by name.
    """
    if pattern:
        needle = pattern.lower()
        return [r for r in rows if needle in r["marker_name"].lower()], f"name pattern {pattern!r}"

    if any(r.get("channel_role") for r in rows):
        return [r for r in rows if r.get("channel_role") == "dna"], "channel_role 'dna'"

    needle = DEFAULT_NUCLEAR_PATTERN.lower()
    return (
        [r for r in rows if needle in r["marker_name"].lower()],
        f"name pattern {DEFAULT_NUCLEAR_PATTERN!r} (no channel_role in the sheet)",
    )


def nuclear_cycle_pair(rows: list[dict[str, Any]], pattern: str | None = None) -> tuple[str, str] | None:
    """Nuclear-stain marker names of the first and last cycle, or None if fewer than two cycles."""
    nuclear, _how = resolve_nuclear_rows(rows, pattern)
    if not nuclear:
        return None
    cycles = sorted({r["cycle_number"] for r in nuclear})
    if len(cycles) < 2:
        return None
    first = next(r["marker_name"] for r in nuclear if r["cycle_number"] == cycles[0])
    last = next(r["marker_name"] for r in nuclear if r["cycle_number"] == cycles[-1])
    return first, last


def cycle_ratio_metrics(first: Any, last: Any, n_bins: int = 64, clip: float = 2.0) -> dict[str, Any]:
    """Per-cell log2 ratio of last-cycle to first-cycle nuclear stain, a tissue-loss signal.

    The histogram is clipped to `[-clip, clip]`, with out-of-range counts reported.
    Cells with zero signal in either cycle are excluded and counted as undefined.
    """
    import numpy as np

    first = np.asarray(first, dtype=np.float64)
    last = np.asarray(last, dtype=np.float64)
    if first.shape != last.shape:
        raise ValueError(f"channel arrays differ in length: {first.shape} vs {last.shape}")
    if first.size == 0:
        raise ValueError("no cells, so no cycle ratio")

    usable = (first > 0) & (last > 0)
    n_undefined = int((~usable).sum())
    if not usable.any():
        return {
            "n_cells": int(first.size),
            "n_undefined": n_undefined,
            "note": "every cell has zero signal in one of the two cycles",
        }

    ratio = np.log2(last[usable] / first[usable])
    counts, edges = np.histogram(np.clip(ratio, -clip, clip), bins=n_bins, range=(-clip, clip))
    return {
        "n_cells": int(first.size),
        "n_usable": int(usable.sum()),
        "n_undefined": n_undefined,
        "median_log2_ratio": float(np.median(ratio)),
        "mean_log2_ratio": float(ratio.mean()),
        "p1_log2_ratio": float(np.percentile(ratio, 1)),
        "p99_log2_ratio": float(np.percentile(ratio, 99)),
        "n_below_half": int((ratio < -1).sum()),
        "fraction_below_half": float((ratio < -1).mean()),
        "histogram": [int(c) for c in counts],
        "histogram_min": -clip,
        "histogram_max": clip,
        "histogram_bin_width": float(edges[1] - edges[0]),
        "n_below_histogram_min": int((ratio < -clip).sum()),
        "n_above_histogram_max": int((ratio > clip).sum()),
    }


def tiff_channel_histograms(path: Path) -> tuple[list[Any], int, list[int]]:
    """Exact per-channel histograms of a pyramidal OME-TIFF's full-resolution level.

    Returns histograms in file order (Ashlar writes no channel names), the dtype's
    maximum value, and the `(c, y, x)` shape.
    """
    import tifffile
    import zarr

    with tifffile.TiffFile(path) as tf:
        if not tf.series:
            raise ValueError(f"{path} has no image series")
        array = zarr.open(tf.series[0].aszarr(level=0), mode="r")
        if array.ndim != 3:
            raise ValueError(f"expected a (c, y, x) OME-TIFF, got shape {array.shape} in {path}")
        hists, dtype_max = channel_histograms(array)
        return hists, dtype_max, list(array.shape)


def sole_image_element(sdata_path: Path) -> str:
    """Name of the store's only image element; raises if there is not exactly one."""
    images = sdata_path / "images"
    if not images.is_dir():
        raise FileNotFoundError(f"{images} does not exist; {sdata_path} is not a SpatialData store")
    elements = sorted(p.name for p in images.iterdir() if (p / "zarr.json").exists() and p.is_dir())
    if len(elements) != 1:
        raise ValueError(f"expected exactly one image element, found {len(elements)}: {elements}")
    return elements[0]


def collect(
    sdata_path: Path,
    min_cell_area: float,
    markers: list[str] | None = None,
    marker_rows: list[dict[str, Any]] | None = None,
    nuclear_pattern: str | None = None,
    before_image: Path | None = None,
    histogram_range: str = "channels-max",
) -> dict[str, Any]:
    """Every metric for one sample; `before_image` and `marker_rows` add optional sections."""
    import numpy as np
    import pyarrow.parquet as pq
    import zarr

    element = sole_image_element(sdata_path)
    table = zarr.open_group(str(sdata_path / "tables" / "table"), mode="r")

    channel_names = [str(n) for n in read_column(table["var"]["_index"])]
    image_labels = image_channel_labels(sdata_path, element)

    areas = read_column(table["obs"]["area"])
    centroids = np.asarray(table["obsm"]["spatial"][:])

    image = zarr.open_array(str(sdata_path / "images" / element / "s0"), mode="r")
    hists, dtype_max = channel_histograms(image)

    out: dict[str, Any] = {
        "sample": sdata_path.stem,
        "store": str(sdata_path),
        "image_element": element,
        "image": {
            "shape_cyx": list(image.shape),
            "dtype": str(image.dtype),
            "n_pyramid_levels": len(
                [p for p in (sdata_path / "images" / element).iterdir() if p.name.startswith("s")]
            ),
        },
        "cells": area_metrics(areas, min_cell_area),
        "channels": {
            "n_channels": len(channel_names),
            "table_names": channel_names,
            "image_names": image_labels,
            "table_matches_image": channel_names == image_labels,
            "per_channel": {},
        },
    }

    if markers is not None:
        out["channels"]["marker_sheet_names"] = markers
        out["channels"]["matches_marker_sheet"] = image_labels == markers

    # Two passes: the shared bound needs every channel's maximum first.
    shared_upper = dtype_max
    if histogram_range == "channels-max":
        maxima = []
        for hist in hists:
            nonzero = np.nonzero(np.asarray(hist))[0]
            maxima.append(int(nonzero[-1]) if len(nonzero) else 0)
        shared_upper = max(1, max(maxima))
    out["channels"]["histogram_upper"] = int(shared_upper)
    out["channels"]["histogram_range"] = histogram_range
    for name, hist in zip(channel_names, hists, strict=True):
        out["channels"]["per_channel"][name] = channel_metrics(hist, dtype_max, histogram_upper=shared_upper)

    if marker_rows is not None:
        roles = {r["marker_name"]: r["channel_role"] for r in marker_rows if r.get("channel_role")}
        compartments = compartments_by_channel(marker_rows)
        for name in channel_names:
            if name in roles:
                out["channels"]["per_channel"][name]["role"] = roles[name]
            if name in compartments:
                out["channels"]["per_channel"][name]["compartment"] = compartments[name]
        by_role = {
            role: names
            for role in ("dna", "marker", "autofluorescence", "blank")
            if (names := channels_with_role(marker_rows, role))
        }
        if by_role:
            out["channels"]["roles"] = by_role
        if compartments:
            out["channels"]["compartments"] = compartments
        unroled = [r["marker_name"] for r in marker_rows if not r.get("channel_role")]
        if unroled:
            out["channels"]["channels_without_role"] = unroled

    if before_image is not None:
        before_hists, before_max, before_shape = tiff_channel_histograms(before_image)
        out["before"] = {
            "image": str(before_image),
            "shape_cyx": before_shape,
            "n_channels": len(before_hists),
            # Ashlar writes no channel names, so a count mismatch cannot be paired.
            "matched_by": "position",
        }
        if len(before_hists) != len(channel_names):
            out["before"]["error"] = (
                f"the pre-subtraction image has {len(before_hists)} channels and the store has "
                f"{len(channel_names)}. Background subtraction removed channels, so they cannot be "
                f"paired by position, and the OME-XML carries no names to pair by instead."
            )
        else:
            for name, hist in zip(channel_names, before_hists, strict=True):
                out["channels"]["per_channel"][name]["before"] = channel_metrics(hist, before_max)

    if marker_rows is not None:
        nuclear_rows, nuclear_how = resolve_nuclear_rows(marker_rows, nuclear_pattern)
        pair = nuclear_cycle_pair(marker_rows, nuclear_pattern)
        cycles = sorted({r["cycle_number"] for r in marker_rows})
        if pair is None:
            # Distinguish "no nuclear channel" from "nuclear channel in one cycle only".
            reason = (
                f"no nuclear channel identified by {nuclear_how}"
                if not nuclear_rows
                else f"nuclear channels found by {nuclear_how} span only "
                f"{len({r['cycle_number'] for r in nuclear_rows})} of {len(cycles)} cycle(s); "
                f"two are needed to compare"
            )
            out["cycle_ratio"] = {
                "available": False,
                "reason": reason,
                "nuclear_selected_by": nuclear_how,
                "nuclear_pattern": nuclear_pattern,
            }
        elif pair[0] not in channel_names or pair[1] not in channel_names:
            out["cycle_ratio"] = {
                "available": False,
                "reason": f"{pair} not both present in the table's channels",
                "nuclear_selected_by": nuclear_how,
                "nuclear_pattern": nuclear_pattern,
            }
        else:
            # X is sopa's per-cell mean intensity; 17 MB for 142k cells.
            x = np.asarray(table["X"][:])
            first_i = channel_names.index(pair[0])
            last_i = channel_names.index(pair[1])
            out["cycle_ratio"] = {
                "available": True,
                "nuclear_selected_by": nuclear_how,
                "nuclear_pattern": nuclear_pattern,
                "first_channel": pair[0],
                "last_channel": pair[1],
                "first_cycle": cycles[0],
                "last_cycle": cycles[-1],
                **cycle_ratio_metrics(x[:, first_i], x[:, last_i]),
            }

    patches_file = sdata_path / "shapes" / "image_patches" / "shapes.parquet"
    if patches_file.exists():
        patches = pq.read_table(patches_file)
        bboxes = np.asarray([list(b) for b in patches.column("bboxes").to_pylist()], dtype=np.float64)
        counts = cells_per_patch(centroids, bboxes)
        out["patches"] = patch_metrics(counts, n_cells=int(len(areas)))
        out["patches"]["cells_per_patch"] = [int(c) for c in counts]
        # ilocs: the patch's (x, y) grid position, so the report can draw the slide layout.
        if "ilocs" in patches.column_names:
            out["patches"]["ilocs"] = [[int(v) for v in i] for i in patches.column("ilocs").to_pylist()]
        out["patches"]["bboxes"] = [[int(v) for v in b] for b in bboxes.tolist()]
    else:
        # None, not zero, so "not tiled" differs from "tiled and empty".
        out["patches"] = None

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sdata", required=True, type=Path, help="SpatialData .zarr store")
    ap.add_argument("--out", required=True, type=Path, help="where to write the metrics JSON")
    ap.add_argument("--markers", type=Path, help="marker sheet CSV, to cross-check channel names")
    ap.add_argument(
        "--min-cell-area",
        type=float,
        default=10.0,
        help="cells below this area in square pixels are counted as degenerate (default: 10)",
    )
    ap.add_argument(
        "--before-image",
        type=Path,
        help="the pre-background-subtraction OME-TIFF, for a before-and-after comparison. "
        "The zarr store only holds the subtracted pixels, so this is the only source.",
    )
    ap.add_argument(
        "--histogram-range",
        choices=("channels-max", "dtype"),
        default="channels-max",
        help="the shared upper bound for every channel's drawn histogram: the brightest "
        "channel's maximum, or the dtype's ceiling. Shared either way, so channels stay "
        "comparable; 'dtype' is the honest detector limit but puts every real channel in the "
        "leftmost few percent of the axis (default: channels-max)",
    )
    ap.add_argument(
        "--nuclear-pattern",
        default=None,
        help="override: substring identifying nuclear-stain channels by name, used to "
        "compare the first and last imaging cycle. Normally unnecessary and unset -- the "
        "marker sheet's channel_role == 'dna' is what identifies the nuclear stain. Pass "
        "this only for a sheet with no channel_role column, or to override a wrong one. "
        f"Without either, falls back to matching {DEFAULT_NUCLEAR_PATTERN!r}.",
    )
    args = ap.parse_args()

    markers = None
    marker_rows = None
    if args.markers:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from set_channel_names import read_marker_names

        markers = read_marker_names(args.markers)
        marker_rows = read_marker_cycles(args.markers)

    metrics = collect(
        args.sdata,
        args.min_cell_area,
        markers,
        marker_rows=marker_rows,
        nuclear_pattern=args.nuclear_pattern,
        before_image=args.before_image,
        histogram_range=args.histogram_range,
    )

    args.out.write_text(json.dumps(metrics, indent=2, sort_keys=False) + "\n")

    cells = metrics["cells"]
    print(f"[qc_metrics] {args.sdata} :: {metrics['image_element']}")
    print(f"  cells      : {cells['n_cells']} ({cells['n_below_min_cell_area']} below min area)")
    print(
        f"  channels   : {metrics['channels']['n_channels']}, table matches image: "
        f"{metrics['channels']['table_matches_image']}"
    )
    if metrics["patches"]:
        p = metrics["patches"]
        print(f"  patches    : {p['n_patches']} ({p['n_empty_patches']} with no cells)")
    if "before" in metrics:
        b = metrics["before"]
        print(f"  before     : {b['n_channels']} channels" + (f" — {b['error']}" if "error" in b else ""))
    ratio = metrics.get("cycle_ratio")
    if ratio and ratio.get("available"):
        print(
            f"  cycles     : {ratio['first_channel']} -> {ratio['last_channel']}, "
            f"median log2 {ratio['median_log2_ratio']:+.2f}, "
            f"{ratio['n_below_half']} cells at least halved"
        )
    elif ratio:
        print(f"  cycles     : unavailable — {ratio['reason']}")
    roles = metrics["channels"].get("roles")
    if roles:
        print("  roles      : " + ", ".join(f"{k}={len(v)}" for k, v in roles.items()))
    if metrics["channels"].get("channels_without_role"):
        print(f"  no role    : {', '.join(metrics['channels']['channels_without_role'])}")
    print(f"  written    : {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
