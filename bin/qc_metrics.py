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


def rebin(hist: Any, n_bins: int, upper: int) -> tuple[list[int], float]:
    """Reduce a full-range histogram to `n_bins` counts over `[0, upper]`.

    For drawing, not for measuring: every number the report states comes from the
    exact histogram, and this only decides the shape of a sparkline. Kept in the
    metrics script rather than the renderer so the renderer never needs the pixels.

    `upper` is the caller's choice of where the drawn range ends, and it matters:
    binning to the dtype's ceiling squeezes every real channel into the left fifth
    of its axis, because channels peak between 3337 and 19200 out of 65535. The bin
    width is returned because it differs per channel, and a chart that does not
    label its axis from it would be lying about the scale.
    """
    import numpy as np

    hist = np.asarray(hist)
    if n_bins < 1:
        raise ValueError(f"n_bins must be at least 1, got {n_bins}")
    if upper < 0:
        raise ValueError(f"upper must be non-negative, got {upper}")

    width = (upper + 1) / n_bins
    counts = np.zeros(n_bins, dtype=np.int64)
    # Sum whole bins with reduceat, which needs the start index of each bin.
    edges = np.minimum((np.arange(n_bins) * width).astype(np.int64), len(hist) - 1)
    summed = np.add.reduceat(hist[: min(len(hist), int(upper) + 1)], edges[edges <= upper])
    counts[: len(summed)] = summed
    return [int(c) for c in counts], float(width)


def channel_metrics(
    hist: Any, dtype_max: int, n_bins: int = 512, histogram_upper: int | None = None
) -> dict[str, Any]:
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
    # One absolute axis shared by every channel, so the drawings are comparable: two
    # channels with the same-looking curve really do have the same intensities. An
    # earlier version binned each channel to its own p99.9, which was readable per row
    # and meaningless across rows.
    #
    # The shared bound is the brightest channel's maximum, not the dtype's ceiling. The
    # ceiling is the honest limit of what the detector could record, but real channels
    # reach a fifth of it at most, so binning there puts every distribution in the
    # leftmost few percent of the axis and all fifteen rows become the same spike --
    # comparable and unreadable. The caller passes the bound; the ceiling is still
    # reported separately as dtype_ceiling.
    upper = dtype_max if histogram_upper is None else histogram_upper
    counts, width = rebin(hist, n_bins, upper)
    metrics["histogram"] = counts
    metrics["histogram_upper"] = upper
    metrics["histogram_bin_width"] = width
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

    # Binned to p99 rather than to the maximum. Cell area is heavy-tailed -- a 12688
    # px2 outlier against a 1009 median -- so binning to the max puts every real cell
    # in the first two bins. The overflow count keeps the tail honest rather than
    # cropping it silently.
    upper = out[_pct_key(99.0)]
    counts, edges = np.histogram(areas, bins=48, range=(0.0, upper))
    out["histogram"] = [int(c) for c in counts]
    out["histogram_upper"] = float(upper)
    out["histogram_bin_width"] = float(edges[1] - edges[0])
    out["n_above_histogram_upper"] = int((areas > upper).sum())
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


def read_marker_cycles(path: Path) -> list[dict[str, Any]]:
    """The marker sheet as rows carrying `cycle_number`, in channel order.

    `read_marker_names` in set_channel_names.py deliberately returns names only,
    because that is all a rename needs. Cycle membership is what tells the first
    imaging round from the last, which is the whole point of the photobleaching
    check, so it is parsed here rather than by widening that function's contract.
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
            }
        )
    out.sort(key=lambda r: r["channel_number"])
    return out


def nuclear_cycle_pair(rows: list[dict[str, Any]], pattern: str = "DAPI") -> tuple[str, str] | None:
    """The nuclear stain of the first and last imaging cycle, by name.

    Every cycle re-images a nuclear stain, which is what makes cross-cycle
    comparison possible at all: the same structure is present in every round, so a
    change in its intensity is a change in the sample or the optics rather than in
    the biology being stained.

    Matched on the marker name rather than on a dedicated column, because the
    samplesheet has no field saying which channel is nuclear. That makes `pattern`
    a real assumption and the reason it is an option rather than a constant. Returns
    None when there is nothing to compare -- a single-cycle run, or no channel whose
    name matches -- and the caller reports the absence rather than inventing a pair.
    """
    needle = pattern.lower()
    nuclear = [r for r in rows if needle in r["marker_name"].lower()]
    if not nuclear:
        return None
    cycles = sorted({r["cycle_number"] for r in nuclear})
    if len(cycles) < 2:
        return None
    first = next(r["marker_name"] for r in nuclear if r["cycle_number"] == cycles[0])
    last = next(r["marker_name"] for r in nuclear if r["cycle_number"] == cycles[-1])
    return first, last


def cycle_ratio_metrics(first: Any, last: Any, n_bins: int = 64, clip: float = 2.0) -> dict[str, Any]:
    """Per-cell log2 ratio of last-cycle to first-cycle nuclear stain.

    A cell that detached, or that sits under tissue lost during a wash, keeps its
    first-cycle signal and loses its last-cycle signal, so its ratio collapses. A
    healthy slide gives a single peak near zero; a slide that shed tissue gives a
    second population to the left of it. Counting cells on that left shoulder is a
    measure of how much of the sample survived processing, which nothing else in
    this pipeline reports.

    log2 rather than a raw quotient so that "half" and "double" sit the same
    distance either side of zero, which a histogram of a raw ratio cannot show. The
    range is clipped rather than trimmed, and the counts at each end are reported
    separately, so a long tail is visible instead of quietly rescaling the axis.

    Cells with no first-cycle signal are excluded and counted: their ratio is not
    large, it is undefined, and averaging them in as a big number would invent
    photobleaching that did not happen.
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
        # Undefined rather than infinite: no first-cycle signal means no baseline.
        "n_undefined": n_undefined,
        "median_log2_ratio": float(np.median(ratio)),
        "mean_log2_ratio": float(ratio.mean()),
        "p1_log2_ratio": float(np.percentile(ratio, 1)),
        "p99_log2_ratio": float(np.percentile(ratio, 99)),
        # A cell at least halved between the first and last cycle.
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

    For the image as it was before background subtraction, which exists only as the
    published OME-TIFF -- the zarr store holds the subtracted version, so a
    before-and-after comparison cannot be made from the store alone.

    Reads one channel at a time. A channel of a real slide is about 500 MB, and
    reading the file as a single array would be 7 GB for no benefit, since each
    channel is reduced to a bin count immediately. Measured at roughly 1.2 seconds
    per channel on the published 6 GB registration output.

    Ashlar writes no channel names into its OME-XML -- verified on that same file,
    which has no `Name` attribute on any `Channel` -- so this returns histograms in
    file order and the caller is responsible for deciding what they line up with.
    """
    import numpy as np
    import tifffile

    with tifffile.TiffFile(path) as tf:
        if not tf.series:
            raise ValueError(f"{path} has no image series")
        level = tf.series[0].levels[0]
        shape = tuple(level.shape)
        dtype = level.dtype

    if len(shape) != 3:
        raise ValueError(f"expected a (c, y, x) OME-TIFF, got shape {shape} in {path}")

    info = np.iinfo(dtype)
    if info.min < 0:
        raise ValueError(f"{path} has signed dtype {dtype}; exact histograms assume unsigned")
    n_bins = int(info.max) + 1

    hists = []
    for c in range(shape[0]):
        plane = tifffile.imread(path, series=0, level=0, key=c)
        hists.append(np.bincount(np.asarray(plane).ravel(), minlength=n_bins))
    return hists, int(info.max), list(shape)


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


def collect(
    sdata_path: Path,
    min_cell_area: float,
    markers: list[str] | None = None,
    marker_rows: list[dict[str, Any]] | None = None,
    nuclear_pattern: str = "DAPI",
    before_image: Path | None = None,
    histogram_range: str = "channels-max",
) -> dict[str, Any]:
    """Every metric for one sample.

    Store-derived by default. `before_image` adds the pre-subtraction OME-TIFF,
    which is the only place the unsubtracted pixels still exist, and `marker_rows`
    adds the cross-cycle nuclear comparison, which needs cycle membership that the
    store does not record.
    """
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

    # Two passes: the shared histogram bound cannot be known until every channel's
    # maximum is, and every channel has to be binned to the same one.
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

    if before_image is not None:
        before_hists, before_max, before_shape = tiff_channel_histograms(before_image)
        out["before"] = {
            "image": str(before_image),
            "shape_cyx": before_shape,
            "n_channels": len(before_hists),
            # Matched by position, and the report says so. Ashlar writes no channel
            # names, so there is nothing to match on -- and if background subtraction
            # dropped channels the two images no longer correspond position for
            # position, which is why a count mismatch refuses rather than guesses.
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
        pair = nuclear_cycle_pair(marker_rows, nuclear_pattern)
        cycles = sorted({r["cycle_number"] for r in marker_rows})
        if pair is None:
            out["cycle_ratio"] = {
                "available": False,
                "reason": (
                    f"need a channel matching {nuclear_pattern!r} in at least two cycles; "
                    f"the sheet has {len(cycles)} cycle(s)"
                ),
                "nuclear_pattern": nuclear_pattern,
            }
        elif pair[0] not in channel_names or pair[1] not in channel_names:
            out["cycle_ratio"] = {
                "available": False,
                "reason": f"{pair} not both present in the table's channels",
                "nuclear_pattern": nuclear_pattern,
            }
        else:
            # X is the mean intensity per cell per channel, which is what sopa's
            # aggregation writes. Reading it whole is 17 MB for 142k cells.
            x = np.asarray(table["X"][:])
            first_i = channel_names.index(pair[0])
            last_i = channel_names.index(pair[1])
            out["cycle_ratio"] = {
                "available": True,
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
        # ilocs is the patch's (x, y) position in the tiling grid, which is what lets
        # a report lay the counts out as the slide rather than as a list of 72
        # numbers. An empty patch means much more when its neighbours are visible.
        if "ilocs" in patches.column_names:
            out["patches"]["ilocs"] = [[int(v) for v in i] for i in patches.column("ilocs").to_pylist()]
        out["patches"]["bboxes"] = [[int(v) for v in b] for b in bboxes.tolist()]
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
        default="DAPI",
        help="substring identifying nuclear-stain channels in the marker sheet, used to "
        "compare the first and last imaging cycle (default: DAPI)",
    )
    args = ap.parse_args()

    markers = None
    marker_rows = None
    if args.markers:
        # Reuse the sheet parser rather than reimplementing the sort-by-channel_number
        # and blank/duplicate rules, which are load-bearing and already tested.
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
    print(f"  written    : {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
