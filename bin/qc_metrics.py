#!/usr/bin/env python3
"""Compute QC metrics for one sample and write them as JSON.

This produces numbers, not a verdict and not a page. Rendering lives in a separate
script that takes this JSON as its only input, so the metrics can be tested without
parsing HTML and the layout can change without touching a measurement.

What this covers that `sopa report` does not. sopa draws cell count, an area
histogram, channel names, per-cell intensity distributions and a UMAP. All of that
is useful and none of it is machine-readable, so an unattended run cannot act on
it. The metrics here are the ones a run needs in order to fail loudly: degenerate
cells, per-channel dynamic range at full resolution, and patches that produced no
cells at all.

Read directly from the store rather than through spatialdata. Same reasoning as
set_channel_names.py: the library pulls in dask and xarray and takes seconds to
import, and everything needed here is a few small arrays plus one streamed pass
over the pixels. zarr, numpy and pyarrow are all already in the sopa image as
spatialdata's own dependencies.

On thresholds. This script deliberately does not decide pass or fail. Every
threshold worth having needs several real datasets behind it, and inventing one
here would bake a guess into the pipeline's exit code. `--min-cell-area` is the
exception: it only classifies, and the count it produces is reported either way.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

# Percentiles reported for every channel and for cell area. p99.9 and p99.99 are
# here because clipping shows up in the extreme tail long before it moves p99: a
# channel with 0.05% of its pixels pinned to the ceiling is already unusable for
# quantification and p99 will not have budged.
PERCENTILES = (1.0, 25.0, 50.0, 75.0, 99.0, 99.9, 99.99)


def percentiles_from_histogram(hist: Any, percentiles: tuple[float, ...] = PERCENTILES) -> dict[str, float]:
    """Exact percentiles of integer data, from a full-range bin count.

    Integer images have few enough distinct values to count every one, so there is
    no reason to approximate or to hold a channel in memory to call np.percentile.
    `hist[v]` is the number of pixels with value `v`, which makes this exact rather
    than interpolated -- and it lets the caller accumulate the histogram over
    streamed row bands.

    Returns the lowest value whose cumulative count reaches the requested fraction,
    which is the "lower" convention rather than numpy's default interpolation. For
    QC that is the honest choice: every number reported is a value that genuinely
    occurs in the image.
    """
    import numpy as np

    hist = np.asarray(hist)
    total = int(hist.sum())
    if total == 0:
        raise ValueError("cannot take percentiles of an empty histogram")

    cumulative = np.cumsum(hist)
    out = {}
    for p in percentiles:
        # searchsorted on the cumulative count finds the first bin where at least
        # this fraction of the data has been accounted for.
        target = p / 100.0 * total
        out[_pct_key(p)] = float(np.searchsorted(cumulative, target, side="left"))
    return out


def _pct_key(p: float) -> str:
    """`99.9` -> `p99_9`, `50.0` -> `p50`. Stable JSON keys for float percentiles."""
    text = f"{p:g}".replace(".", "_")
    return f"p{text}"


def effective_bit_depth(max_value: int) -> int:
    """Bits actually used by the data, as opposed to the bits the dtype provides.

    A 12-bit camera writing into uint16 leaves the top four bits permanently zero.
    Reporting this is the difference between a saturation check that works and one
    that is decorative: on real pipeline output the per-channel maxima came in at
    920 to 13572 against a uint16 ceiling of 65535, so a "fraction of pixels at
    65535" check reads 0.0 on every channel and looks like a pass. The headroom is
    what a human needs to see.

    Rounds up to a whole bit and never reports less than 8, since no imaging
    detector produces less and a smaller number means the channel is nearly empty
    rather than genuinely 4-bit.
    """
    if max_value < 0:
        raise ValueError(f"max_value must be non-negative, got {max_value}")
    if max_value == 0:
        return 0
    return max(8, math.ceil(math.log2(max_value + 1)))


def channel_metrics(hist: Any, dtype_max: int) -> dict[str, Any]:
    """Per-channel intensity metrics from one channel's full-range histogram.

    `fraction_at_dtype_ceiling` is true saturation: pixels the detector could not
    represent. It is the metric that matters and it is usually zero.
    `headroom_stops` is how many bits of the dtype went unused, and is the metric
    that is usually interesting -- a channel using 14 of 16 bits is fine, one using
    9 is throwing away three quarters of its precision.

    `fraction_zero` earns its place on this pipeline specifically. Background
    subtraction clips at zero, so a channel that comes out of backsub mostly zero
    has had its signal subtracted away, and that is invisible in a mean intensity.
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
    return metrics


def area_metrics(areas: Any, min_cell_area: float) -> dict[str, Any]:
    """Cell area distribution, and how many cells are too small to be cells.

    Real pipeline output had a minimum area of 4.3 px squared against a median of
    1009, which is segmentation debris rather than biology. A count of those is a
    far better signal than the histogram sopa already draws, because it is one
    number that can be compared between runs.
    """
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
    return out


def cells_per_patch(centroids: Any, bboxes: Any) -> Any:
    """How many cell centroids fall inside each patch bounding box.

    Counts centroids rather than intersecting boundaries, because a centroid is one
    point and gives each cell exactly one home. Patches overlap by design
    (`patch_overlap_pixel`), so a cell in an overlap region is counted by both
    patches it lands in and the counts sum to more than the cell total. That is
    correct for the question being asked -- "did this patch produce cells" -- and
    the caller reports the overlap rather than hiding it.

    A patch with zero cells is the signal worth having. It means either genuinely
    empty background, which is fine and common at a slide's edges, or a segmentation
    task that silently produced nothing, which is not.
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
        # Half-open on the upper edge so a centroid on a shared boundary belongs to
        # one patch rather than being counted twice on top of the overlap.
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
        # Sums past the cell total because patches overlap. Reported so the excess
        # is visible rather than looking like a counting bug.
        "centroid_assignments": int(counts.sum()),
        "n_cells": n_cells,
    }


# --------------------------------------------------------------------------------
# Reading the store.
#
# AnnData encodes a dataframe column three different ways depending on its dtype,
# and the group attributes say which. Handling all three in one place keeps that
# detail out of the metric functions, which then only ever see plain arrays.
# --------------------------------------------------------------------------------


def read_column(node: Any) -> Any:
    """One AnnData obs/var column, whatever encoding it uses.

    Verified against real pipeline output: `obs/area` is a plain array, `obs/region`
    and `obs/slide` are categorical (`categories` plus integer `codes`), and
    `var/_index` and `obs/cell_id` are nullable strings (`values` plus a `mask`).
    Guessing from the group's contents instead of its `encoding-type` would work
    today and break on the first column that adds a key.
    """
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
    """Channel names as written on the image element, from `omero.channels[].label`.

    The same few kilobytes of metadata `set_channel_names.py` writes. Read here
    rather than imported from that script: both are standalone executables on PATH
    inside a container, and importing one from the other would make this one fail
    for a reason that has nothing to do with QC.
    """
    meta = sdata_path / "images" / element / "zarr.json"
    if not meta.exists():
        raise FileNotFoundError(f"{meta} does not exist, so '{element}' is not an image element")
    attrs = json.loads(meta.read_text()).get("attributes", {})
    channels = attrs.get("ome", {}).get("omero", {}).get("channels")
    if channels is None:
        raise ValueError(f"{meta} has no attributes.ome.omero.channels; the store layout has changed")
    return [c["label"] for c in channels]


def channel_histograms(array: Any, band_rows: int = 2048) -> tuple[list[Any], int]:
    """Exact per-channel value histograms, streamed a row band at a time.

    Full resolution is not a compromise here, it is a requirement. Saturation and
    clipping are per-pixel extremes, and every pyramid level below s0 averages
    neighbours, so a clipped pixel stops being clipped the moment it is
    downsampled. Measuring on s1 would produce a plausible number that is wrong in
    the safe direction.

    Streaming keeps this affordable. A real 15-channel 11295x21798 uint16 image is
    7.4 GB in full, but read as row bands and reduced to a bin count immediately it
    never holds more than one band, and a complete pass measured about 6 seconds on
    a laptop against the published store.

    Returns the histograms and the dtype's maximum representable value, which is
    what `channel_metrics` needs to tell true saturation from unused headroom.
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


def sole_image_element(sdata_path: Path) -> str:
    """The store's only image element.

    Same guard as `set_channel_names.py` and for the same reason: after conversion
    there is exactly one, and on the TMA path each core is its own store. "Exactly
    one image" is the property this pipeline actually maintains, so depending on it
    is safer than naming an element after something upstream might rename.
    """
    images = sdata_path / "images"
    if not images.is_dir():
        raise FileNotFoundError(f"{images} does not exist; {sdata_path} is not a SpatialData store")
    elements = sorted(p.name for p in images.iterdir() if (p / "zarr.json").exists() and p.is_dir())
    if len(elements) != 1:
        raise ValueError(f"expected exactly one image element, found {len(elements)}: {elements}")
    return elements[0]


def collect(sdata_path: Path, min_cell_area: float, markers: list[str] | None) -> dict[str, Any]:
    """Every store-derived metric for one sample."""
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
            # A mismatch here means the table and the image disagree about what was
            # measured, which makes every per-cell intensity ambiguous. It has never
            # happened, and it is exactly the kind of thing that stays never-happened
            # only while something checks.
            "table_matches_image": channel_names == image_labels,
            "per_channel": {},
        },
    }

    if markers is not None:
        out["channels"]["marker_sheet_names"] = markers
        out["channels"]["matches_marker_sheet"] = image_labels == markers

    for name, hist in zip(channel_names, hists, strict=True):
        out["channels"]["per_channel"][name] = channel_metrics(hist, dtype_max)

    patches_file = sdata_path / "shapes" / "image_patches" / "shapes.parquet"
    if patches_file.exists():
        patches = pq.read_table(patches_file)
        bboxes = np.asarray([list(b) for b in patches.column("bboxes").to_pylist()], dtype=np.float64)
        counts = cells_per_patch(centroids, bboxes)
        out["patches"] = patch_metrics(counts, n_cells=int(len(areas)))
        out["patches"]["cells_per_patch"] = [int(c) for c in counts]
    else:
        # Segmentation without tiling leaves no patch element. Absent rather than
        # zero, so a reader can tell "not tiled" from "tiled and empty".
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
    args = ap.parse_args()

    markers = None
    if args.markers:
        # Reuse the sheet parser rather than reimplementing the sort-by-channel_number
        # and blank/duplicate rules, which are load-bearing and already tested.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from set_channel_names import read_marker_names

        markers = read_marker_names(args.markers)

    metrics = collect(args.sdata, args.min_cell_area, markers)

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
    print(f"  written    : {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
