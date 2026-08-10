#!/usr/bin/env python3
"""Render the QC images and cluster the cells, writing PNGs and a JSON index.

Separate from qc_metrics.py on purpose. That script is a 23-second pass over the
pixels and imports only zarr, numpy and pyarrow. This one builds a nearest-neighbour
graph over every cell and rasterises polygons, so it takes minutes and needs scanpy,
shapely and PIL. Keeping them apart means the fast numbers do not wait on the slow
pictures, and a failure here does not cost the metrics.

Nothing new is needed in the container. scanpy and igraph are direct sopa
dependencies, so Leiden runs through scanpy's igraph flavour with no leidenalg;
geopandas brings shapely for the segmentation polygons, and spatialdata-plot brings
matplotlib and therefore PIL.

What it produces, and why each one is a check rather than a picture:

Segmentation crops. Numbers cannot show whether a mask follows a cell. Windows are
picked across the density range instead of at random, because segmentation fails
differently where cells are packed than where they are sparse, and a random sample
of a mostly-empty slide is mostly empty background.

Cluster heatmap. Cells are grouped on their marker intensities alone, with no
spatial input, so the clusters are a statement about the staining. A run whose
markers did not work produces one undifferentiated blob, which is visible here and
in nothing else the report shows.

Representative cells. A cluster is only trustworthy if its cells look like what its
marker profile claims, so each cluster shows two cells in its own top marker beside
the nuclear stain, with the mask drawn on.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Marker in magenta, nuclear in green: the conventional two-colour microscopy pair,
# and the one that stays distinguishable under the common colour-vision deficiencies,
# unlike red and green. The mask goes on in white over both.
MARKER_RGB = (1.0, 0.0, 1.0)
NUCLEAR_RGB = (0.0, 1.0, 0.0)
# Cyan on the grayscale crops, because the base image is grey -- r == g == b at
# every pixel -- so a saturated hue cannot be produced by the data and can never be
# mistaken for a bright nucleus. White would be, and the mask sitting on the exact
# structure it outlines is where that confusion costs most.
CROP_MASK_RGB = (0, 229, 255)
# White on the two-colour snapshots, where magenta and green already occupy the
# saturated hues.
MASK_RGB = (255, 255, 255)


def read_boundaries(sdata_path: Path, name: str = "cellpose_boundaries") -> Any:
    """The segmentation polygons, as a GeoDataFrame indexed like the table's rows.

    Read with geopandas rather than by decoding WKB here: the file is a GeoParquet
    written by geopandas, and its own reader is the only thing guaranteed to agree
    with it about geometry and index order.
    """
    import geopandas as gpd

    path = sdata_path / "shapes" / name / "shapes.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist, so there are no boundaries to draw")
    return gpd.read_parquet(path)


def window_counts(centroids: Any, shape_yx: tuple[int, int], window: int) -> Any:
    """Cells per non-overlapping window over the whole image.

    The grid used to choose what to show. Non-overlapping unlike the pipeline's
    patches, because these windows are picture frames rather than work units and a
    cell counted twice would distort the density ranking.
    """
    import numpy as np

    height, width = shape_yx
    nx = max(1, int(np.ceil(width / window)))
    ny = max(1, int(np.ceil(height / window)))
    ix = np.clip((centroids[:, 0] // window).astype(int), 0, nx - 1)
    iy = np.clip((centroids[:, 1] // window).astype(int), 0, ny - 1)
    counts = np.zeros((ny, nx), dtype=np.int64)
    np.add.at(counts, (iy, ix), 1)
    return counts


def pick_windows(counts: Any, n: int = 6) -> list[dict[str, Any]]:
    """Windows spanning the density range, labelled by where they sit in it.

    Deliberately not a random sample. Segmentation fails differently in packed
    tissue, where masks merge, than at a sparse edge, where debris gets segmented as
    cells, and a random draw from a slide that is mostly background returns mostly
    background. Empty windows are excluded: there is nothing to inspect in them and
    the count already reports how many there are.

    Picks evenly across the ranking rather than taking the top n, so the set covers
    dense, middling and sparse instead of six variations of crowded.
    """
    import numpy as np

    ys, xs = np.nonzero(counts)
    if len(ys) == 0:
        return []
    values = counts[ys, xs]
    order = np.argsort(values)[::-1]
    n = min(n, len(order))
    # Evenly spaced positions in the sorted ranking, ends included.
    picks = np.linspace(0, len(order) - 1, n).round().astype(int)

    out = []
    for rank_position in picks:
        i = order[rank_position]
        fraction = rank_position / max(1, len(order) - 1)
        if fraction <= 0.25:
            band = "dense"
        elif fraction <= 0.75:
            band = "medium"
        else:
            band = "sparse"
        out.append(
            {
                "grid_x": int(xs[i]),
                "grid_y": int(ys[i]),
                "n_cells": int(counts[ys[i], xs[i]]),
                "density_band": band,
                "density_rank": int(rank_position) + 1,
                "n_nonempty_windows": int(len(order)),
            }
        )
    return out


def stretch(plane: Any, lo: float, hi: float) -> Any:
    """Map an intensity window onto 0..255 with a stated pair of bounds.

    Linear between two explicit percentiles, not auto-levelled per crop. Every crop
    in a set uses the same pair, so a dim region looks dim instead of being
    brightened into looking like a dense one, and the bounds go into the JSON so the
    picture states how it was made.
    """
    import numpy as np

    if hi <= lo:
        hi = lo + 1.0
    scaled = (np.asarray(plane, dtype=np.float32) - lo) / (hi - lo)
    return (np.clip(scaled, 0.0, 1.0) * 255.0).astype(np.uint8)


def composite(planes: list[tuple[Any, tuple[float, float, float]]]) -> Any:
    """Additively combine 8-bit planes, each through its own RGB weight."""
    import numpy as np

    height, width = planes[0][0].shape
    rgb = np.zeros((height, width, 3), dtype=np.float32)
    for plane, weight in planes:
        for i, w in enumerate(weight):
            if w:
                rgb[:, :, i] += np.asarray(plane, dtype=np.float32) * w
    return np.clip(rgb, 0, 255).astype(np.uint8)


def draw_outlines(
    image: Any, geometries: Any, x0: int, y0: int, colour: tuple[int, int, int] = MASK_RGB
) -> int:
    """Draw polygon boundaries, outline only, over a PIL image.

    Outline rather than fill, because the point is to see whether the mask follows
    the cell it claims: a filled mask hides the pixels a reader is trying to judge.

    Coordinates are shifted into the window rather than the polygons being clipped to
    it. PIL discards what falls outside, and a cell straddling the edge should show
    the part of its outline that is inside the frame.
    """
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    drawn = 0
    for geom in geometries:
        if geom is None or geom.is_empty:
            continue
        parts = geom.geoms if geom.geom_type.startswith("Multi") else [geom]
        for part in parts:
            if not hasattr(part, "exterior") or part.exterior is None:
                continue
            points = [(x - x0, y - y0) for x, y in part.exterior.coords]
            if len(points) < 2:
                continue
            draw.line(points + [points[0]], fill=colour, width=1)
            drawn += 1
    return drawn


def render_crops(
    sdata_path: Path,
    element: str,
    channel_index: int,
    channel_name: str,
    centroids: Any,
    boundaries: Any,
    out_dir: Path,
    window: int = 1000,
    n_windows: int = 6,
) -> list[dict[str, Any]]:
    """Segmentation crops across the density range, one PNG each."""
    import numpy as np
    import zarr
    from PIL import Image

    image = zarr.open_array(str(sdata_path / "images" / element / "s0"), mode="r")
    _, height, width = image.shape
    counts = window_counts(centroids, (height, width), window)
    picks = pick_windows(counts, n_windows)
    if not picks:
        return []

    # One pair of display bounds for the whole set, taken from the windows actually
    # shown, so the crops are comparable with each other.
    planes = []
    for pick in picks:
        x0, y0 = pick["grid_x"] * window, pick["grid_y"] * window
        x1, y1 = min(x0 + window, width), min(y0 + window, height)
        planes.append((pick, x0, y0, np.asarray(image[channel_index, y0:y1, x0:x1])))
    pooled = np.concatenate([p[3].ravel() for p in planes])
    lo, hi = (float(np.percentile(pooled, 1.0)), float(np.percentile(pooled, 99.5)))

    sindex = boundaries.sindex
    out = []
    for pick, x0, y0, plane in planes:
        rgb = composite([(stretch(plane, lo, hi), (1.0, 1.0, 1.0))])
        img = Image.fromarray(rgb, mode="RGB")
        hits = sindex.query(_box(x0, y0, x0 + plane.shape[1], y0 + plane.shape[0]))
        n_drawn = draw_outlines(img, boundaries.geometry.iloc[hits], x0, y0, CROP_MASK_RGB)
        name = f"crop_{pick['density_band']}_{pick['grid_x']}_{pick['grid_y']}.png"
        img.save(out_dir / name, optimize=True)
        out.append(
            {
                **pick,
                "file": name,
                "x0": int(x0),
                "y0": int(y0),
                "width": int(plane.shape[1]),
                "height": int(plane.shape[0]),
                "channel": channel_name,
                "display_min": lo,
                "display_max": hi,
                "n_outlines": int(n_drawn),
            }
        )
    return out


def _box(x0: float, y0: float, x1: float, y1: float) -> Any:
    from shapely.geometry import box

    return box(x0, y0, x1, y1)


def cluster_cells(
    x: Any,
    channel_names: list[str],
    use_channels: list[str],
    cofactor: float,
    resolution: float,
    max_cells: int,
    seed: int = 0,
) -> dict[str, Any]:
    """Leiden clusters on arcsinh-transformed mean intensities.

    arcsinh rather than log: it is defined at zero, which matters because background
    subtraction leaves a great many exact zeros, and log would need a pseudocount
    chosen out of thin air. The cofactor sets where the curve stops being linear and
    starts being logarithmic, so it belongs near the noise level and is an option
    rather than a constant.

    Scaled per channel afterwards, because Leiden works on distances and an unscaled
    matrix would let whichever marker happens to be brightest dominate the graph.

    Subsamples above `max_cells`. The graph is quadratic in spirit and 142k cells
    costs minutes; a QC view of cluster structure does not improve past a few tens of
    thousands. The count is reported so the figure is not mistaken for all cells.
    """
    import numpy as np

    keep = [channel_names.index(c) for c in use_channels]
    values = np.asarray(x, dtype=np.float64)[:, keep]

    rng = np.random.default_rng(seed)
    n_total = values.shape[0]
    if 0 < max_cells < n_total:
        sample = np.sort(rng.choice(n_total, size=max_cells, replace=False))
    else:
        sample = np.arange(n_total)
    values = values[sample]

    import anndata as ad
    import scanpy as sc

    adata = ad.AnnData(np.arcsinh(values / cofactor).astype(np.float32))
    adata.var_names = list(use_channels)
    sc.pp.scale(adata, max_value=10)
    sc.pp.neighbors(adata, n_neighbors=15, use_rep="X", random_state=seed)
    # flavour="igraph" uses igraph's own implementation, which is a direct sopa
    # dependency; the default flavour would need leidenalg, which is not.
    sc.tl.leiden(
        adata,
        resolution=resolution,
        flavor="igraph",
        n_iterations=2,
        directed=False,
        random_state=seed,
    )
    labels = adata.obs["leiden"].to_numpy()
    order = sorted({str(v) for v in labels}, key=lambda s: int(s))

    # Mean scaled value per cluster per marker: this is the z-scored matrix the
    # heatmap shows, so a cell above or below the slide's average reads as such.
    scaled = np.asarray(adata.X)
    matrix = []
    sizes = []
    for cluster in order:
        mask = labels == cluster
        sizes.append(int(mask.sum()))
        matrix.append([float(v) for v in scaled[mask].mean(axis=0)])

    # The argmax of an all-negative row is the least-negative marker, not a positive
    # one. Six clusters on the published run are below the slide average on every
    # marker -- dim cells, largely ones background subtraction drove to exact zeros --
    # and naming one of them "top marker" would read as "these are CD8 cells" when
    # they are dim for everything. The channel is still needed to render a snapshot,
    # so it is kept and flagged rather than dropped.
    top_markers = [use_channels[int(np.argmax(row))] for row in matrix]
    top_above_average = [bool(max(row) > 0) for row in matrix]
    return {
        "resolution": resolution,
        "arcsinh_cofactor": cofactor,
        "n_cells_clustered": int(len(sample)),
        "n_cells_total": int(n_total),
        "subsampled": bool(len(sample) < n_total),
        "channels_used": list(use_channels),
        "clusters": order,
        "cluster_sizes": sizes,
        "top_marker": top_markers,
        "top_marker_above_average": top_above_average,
        "matrix": matrix,
        "_sample_index": sample,
        "_labels": labels,
        "_scaled": scaled,
    }


def representative_cells(
    clustering: dict[str, Any],
    n_per_cluster: int = 2,
) -> dict[str, list[int]]:
    """The cells nearest each cluster's centre, as row indices into the table.

    Nearest the centroid rather than the brightest for its top marker: the brightest
    cell in a cluster is usually its most extreme, and an extreme is exactly what
    should not be shown as representative.
    """
    import numpy as np

    scaled = clustering["_scaled"]
    labels = clustering["_labels"]
    sample = clustering["_sample_index"]
    out = {}
    for cluster in clustering["clusters"]:
        mask = labels == cluster
        members = np.nonzero(mask)[0]
        if len(members) == 0:
            out[cluster] = []
            continue
        centre = scaled[members].mean(axis=0)
        distance = np.linalg.norm(scaled[members] - centre, axis=1)
        nearest = members[np.argsort(distance)[:n_per_cluster]]
        out[cluster] = [int(sample[i]) for i in nearest]
    return out


def render_cell_snapshots(
    sdata_path: Path,
    element: str,
    channel_names: list[str],
    nuclear_channel: str,
    clustering: dict[str, Any],
    picks: dict[str, list[int]],
    centroids: Any,
    boundaries: Any,
    out_dir: Path,
    size: int = 128,
) -> list[dict[str, Any]]:
    """Two cells per cluster, in the cluster's top marker and the nuclear stain."""
    import numpy as np
    import zarr
    from PIL import Image

    image = zarr.open_array(str(sdata_path / "images" / element / "s0"), mode="r")
    _, height, width = image.shape
    nuclear_index = channel_names.index(nuclear_channel)
    half = size // 2

    out = []
    for cluster, marker in zip(clustering["clusters"], clustering["top_marker"], strict=True):
        marker_index = channel_names.index(marker)
        for rank, cell in enumerate(picks.get(cluster, [])):
            cx, cy = float(centroids[cell, 0]), float(centroids[cell, 1])
            x0 = int(min(max(0, cx - half), max(0, width - size)))
            y0 = int(min(max(0, cy - half), max(0, height - size)))
            x1, y1 = min(x0 + size, width), min(y0 + size, height)

            marker_plane = np.asarray(image[marker_index, y0:y1, x0:x1])
            nuclear_plane = np.asarray(image[nuclear_index, y0:y1, x0:x1])
            rgb = composite(
                [
                    (
                        stretch(
                            marker_plane,
                            float(np.percentile(marker_plane, 1)),
                            max(float(np.percentile(marker_plane, 99.5)), 1.0),
                        ),
                        MARKER_RGB,
                    ),
                    (
                        stretch(
                            nuclear_plane,
                            float(np.percentile(nuclear_plane, 1)),
                            max(float(np.percentile(nuclear_plane, 99.5)), 1.0),
                        ),
                        NUCLEAR_RGB,
                    ),
                ]
            )
            img = Image.fromarray(rgb, mode="RGB")
            hits = boundaries.sindex.query(_box(x0, y0, x1, y1))
            draw_outlines(img, boundaries.geometry.iloc[hits], x0, y0)
            name = f"cell_c{cluster}_{rank}.png"
            img.save(out_dir / name, optimize=True)
            out.append(
                {
                    "cluster": cluster,
                    "file": name,
                    "marker": marker,
                    "nuclear": nuclear_channel,
                    "cell_index": int(cell),
                    "x0": x0,
                    "y0": y0,
                    "width": int(x1 - x0),
                    "height": int(y1 - y0),
                }
            )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sdata", required=True, type=Path, help="SpatialData .zarr store")
    ap.add_argument("--out-dir", required=True, type=Path, help="directory for the PNGs and index")
    ap.add_argument("--markers", type=Path, help="marker sheet CSV, for cycle and background columns")
    ap.add_argument("--nuclear-pattern", default="DAPI", help="substring naming nuclear channels")
    ap.add_argument("--window", type=int, default=1000, help="crop size in pixels (default: 1000)")
    ap.add_argument("--n-windows", type=int, default=6, help="how many crops (default: 6)")
    ap.add_argument("--resolution", type=float, default=0.5, help="Leiden resolution (default: 0.5)")
    ap.add_argument(
        "--arcsinh-cofactor",
        type=float,
        default=150.0,
        help="arcsinh cofactor; set near the noise level (default: 150)",
    )
    ap.add_argument(
        "--max-cells",
        type=int,
        default=50000,
        help="subsample for clustering, 0 for all cells (default: 50000)",
    )
    ap.add_argument("--skip-clustering", action="store_true", help="render crops only")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import numpy as np
    import zarr
    from qc_metrics import read_column, read_marker_cycles, sole_image_element

    args.out_dir.mkdir(parents=True, exist_ok=True)
    element = sole_image_element(args.sdata)
    table = zarr.open_group(str(args.sdata / "tables" / "table"), mode="r")
    channel_names = [str(n) for n in read_column(table["var"]["_index"])]
    centroids = np.asarray(table["obsm"]["spatial"][:])
    boundaries = read_boundaries(args.sdata)

    nuclear = [c for c in channel_names if args.nuclear_pattern.lower() in c.lower()]
    if not nuclear:
        raise ValueError(
            f"no channel matching {args.nuclear_pattern!r}; pass --nuclear-pattern to name the "
            f"nuclear stain. Channels present: {channel_names}"
        )
    nuclear_channel = nuclear[0]

    index: dict[str, Any] = {
        "sample": args.sdata.stem,
        "image_element": element,
        "nuclear_channel": nuclear_channel,
        "crop_mask_colour": "cyan",
        "mask_colour": "white",
        "marker_colour": "magenta",
        "nuclear_colour": "green",
    }

    print(f"[qc_images] {args.sdata} :: {element}")
    index["crops"] = render_crops(
        args.sdata,
        element,
        channel_names.index(nuclear_channel),
        nuclear_channel,
        centroids,
        boundaries,
        args.out_dir,
        window=args.window,
        n_windows=args.n_windows,
    )
    print(f"  crops      : {len(index['crops'])} of {args.window}x{args.window} px")

    if not args.skip_clustering:
        # Background channels and the nuclear stains are excluded from clustering.
        # A background channel is one another channel subtracts, so it is an
        # instrument reading rather than a phenotype, and nuclear stain is present in
        # every cell by construction: neither separates cell types, and both would
        # pull the graph toward staining intensity instead.
        excluded = set(nuclear)
        if args.markers:
            rows = read_marker_cycles(args.markers)
            import csv

            with args.markers.open(newline="") as fh:
                for r in csv.DictReader(fh):
                    if (r.get("background") or "").strip():
                        excluded.add(r["background"].strip())
            del rows
        use = [c for c in channel_names if c not in excluded]
        if len(use) < 2:
            raise ValueError(f"only {len(use)} channel(s) left to cluster on after excluding {excluded}")

        x = np.asarray(table["X"][:])
        clustering = cluster_cells(
            x,
            channel_names,
            use,
            cofactor=args.arcsinh_cofactor,
            resolution=args.resolution,
            max_cells=args.max_cells,
        )
        picks = representative_cells(clustering)
        print(
            f"  clusters   : {len(clustering['clusters'])} at resolution {args.resolution} "
            f"on {clustering['n_cells_clustered']:,} cells, {len(use)} markers"
        )
        index["snapshots"] = render_cell_snapshots(
            args.sdata,
            element,
            channel_names,
            nuclear_channel,
            clustering,
            picks,
            centroids,
            boundaries,
            args.out_dir,
        )
        print(f"  snapshots  : {len(index['snapshots'])}")
        index["clustering"] = {k: v for k, v in clustering.items() if not k.startswith("_")}
        index["clustering"]["excluded_channels"] = sorted(excluded)

    out_json = args.out_dir / "qc_images.json"
    out_json.write_text(json.dumps(index, indent=2) + "\n")
    print(f"  written    : {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
