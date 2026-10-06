#!/usr/bin/env python3
"""Render QC images from a SpatialData store and Leiden-cluster its cells.

Reads the store and optional marker sheet; writes segmentation crops, per-cluster cell
snapshots and qc_images.json. Kept apart from qc_metrics.py because it takes minutes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Magenta and green stay distinguishable under common colour-vision deficiencies.
MARKER_RGB = (1.0, 0.0, 1.0)
NUCLEAR_RGB = (0.0, 1.0, 0.0)
# Saturated red cannot occur in the greyscale crop, so the mask never looks like data.
CROP_MASK_RGBA = (208, 59, 59, 204)
MASK_RGB = (255, 255, 255)
TARGET_MASK_RGB = (255, 214, 0)


def _qc_metrics():
    """Import the sibling qc_metrics module, adding bin/ to sys.path once."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import qc_metrics

    return qc_metrics


def select_nuclear_channels(
    channel_names: list[str],
    marker_rows: list[dict[str, Any]] | None,
    pattern: str | None = None,
) -> tuple[list[str], str]:
    """Return the store's nuclear channels and a description of how they were found.

    The sheet's nuclear rows are intersected with `channel_names` (in store order),
    since removed or subtracted channels are absent from the table. Returns an empty
    list rather than raising so the caller can name the route in its error.
    """
    qc_metrics = _qc_metrics()

    if marker_rows is None:
        chosen = pattern or qc_metrics.DEFAULT_NUCLEAR_PATTERN
        needle = chosen.lower()
        return (
            [c for c in channel_names if needle in c.lower()],
            f"name pattern {chosen!r} (no marker sheet given)",
        )

    nuclear_rows, how = qc_metrics.resolve_nuclear_rows(marker_rows, pattern)
    wanted = {r["marker_name"] for r in nuclear_rows}
    return [c for c in channel_names if c in wanted], how


def clustering_exclusions(nuclear: list[str], marker_rows: list[dict[str, Any]] | None) -> dict[str, str]:
    """Map channels held out of clustering (nuclear, autofluorescence, blank, background) to the reason."""
    channels_with_role = _qc_metrics().channels_with_role

    excluded = {c: "nuclear stain" for c in nuclear}
    if marker_rows is not None:
        for role in ("autofluorescence", "blank"):
            for name in channels_with_role(marker_rows, role):
                excluded.setdefault(name, f"channel_role {role!r}")
        for row in marker_rows:
            if row.get("background"):
                excluded.setdefault(row["background"], "named as another channel's background")
    return excluded


def read_boundaries(sdata_path: Path, name: str = "cellpose_boundaries") -> Any:
    """Read the segmentation polygons as a GeoDataFrame indexed like the table's rows."""
    import geopandas as gpd

    path = sdata_path / "shapes" / name / "shapes.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist, so there are no boundaries to draw")
    return gpd.read_parquet(path)


def window_counts(centroids: Any, shape_yx: tuple[int, int], window: int) -> Any:
    """Count cells per non-overlapping window; returns a (ny, nx) array.

    `centroids` is (n, 2) in x, y order; `shape_yx` is (height, width) in pixels.
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
    """Pick n non-empty windows evenly across the density ranking, labelled dense/medium/sparse.

    Not random: segmentation fails differently in packed and sparse tissue, and a
    random draw from a mostly empty slide is mostly background.
    """
    import numpy as np

    ys, xs = np.nonzero(counts)
    if len(ys) == 0:
        return []
    values = counts[ys, xs]
    order = np.argsort(values)[::-1]
    n = min(n, len(order))
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
    """Linearly map intensities between lo and hi onto uint8 0..255."""
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
    image: Any,
    geometries: Any,
    x0: int,
    y0: int,
    colour: tuple[int, ...] = MASK_RGB,
    width: int = 1,
) -> int:
    """Draw polygon outlines over a PIL image offset by (x0, y0); returns the number drawn.

    Polygons are shifted, not clipped; PIL discards what falls outside the frame.
    """
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image, "RGBA" if len(colour) == 4 else None)
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
            draw.line(points + [points[0]], fill=colour, width=width)
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

    # One pair of display bounds for the whole set so the crops are comparable.
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
        img = img.convert("RGBA")
        n_drawn = draw_outlines(img, boundaries.geometry.iloc[hits], x0, y0, CROP_MASK_RGBA)
        img = img.convert("RGB")
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


def cluster_tree(labels_by_resolution: list[Any], resolutions: list[float]) -> dict[str, Any]:
    """Build a clustree-style graph: one level per resolution, edges for cells moving between clusters."""
    import numpy as np

    levels = []
    for r, labels in zip(resolutions, labels_by_resolution, strict=True):
        clusters = sorted({str(v) for v in labels}, key=lambda s: int(s))
        levels.append(
            {
                "resolution": r,
                "clusters": clusters,
                "sizes": [int((labels == c).sum()) for c in clusters],
            }
        )

    edges = []
    for i in range(len(labels_by_resolution) - 1):
        a, b = labels_by_resolution[i], labels_by_resolution[i + 1]
        for ca in levels[i]["clusters"]:
            mask = a == ca
            if not mask.any():
                continue
            sub, counts = np.unique(b[mask], return_counts=True)
            for cb, n in zip(sub, counts, strict=True):
                edges.append(
                    {
                        "level": i,
                        "from": str(ca),
                        "to": str(cb),
                        "n_cells": int(n),
                        "fraction_of_source": float(n / mask.sum()),
                    }
                )
    return {"levels": levels, "edges": edges}


def cluster_cells(
    x: Any,
    channel_names: list[str],
    use_channels: list[str],
    cofactor: float,
    resolutions: list[float],
    max_cells: int,
    requested_resolution: float | None = None,
    stability_floor: float = 0.9,
    seed: int = 0,
) -> dict[str, Any]:
    """Leiden-cluster cells on arcsinh-transformed, per-channel scaled mean intensities.

    Args:
        x: cells by channels matrix, columns ordered as `channel_names`.
        cofactor: fixed arcsinh cofactor; 0 or less derives one per channel.
        max_cells: subsample size; 0 clusters all cells.
        requested_resolution: overrides the stability-based choice when not None.

    Returns:
        A dict of results; keys starting with "_" hold arrays for later rendering.
    """
    import numpy as np

    keep = [channel_names.index(c) for c in use_channels]
    values = np.asarray(x, dtype=np.float64)[:, keep]

    # Per-channel cofactor (median of positive values) because noise floors differ
    # over tenfold between channels (CD38 peaks at 3,337, 647_bg at 19,200).
    if cofactor > 0:
        cofactors = [float(cofactor)] * values.shape[1]
    else:
        cofactors = []
        for j in range(values.shape[1]):
            positive = values[:, j][values[:, j] > 0]
            cofactors.append(float(max(1.0, np.median(positive))) if positive.size else 1.0)

    rng = np.random.default_rng(seed)
    n_total = values.shape[0]
    if 0 < max_cells < n_total:
        sample = np.sort(rng.choice(n_total, size=max_cells, replace=False))
    else:
        sample = np.arange(n_total)
    values = values[sample]

    import anndata as ad
    import scanpy as sc

    adata = ad.AnnData(np.arcsinh(values / np.asarray(cofactors)).astype(np.float32))
    adata.var_names = list(use_channels)
    sc.pp.scale(adata, max_value=10)
    sc.pp.neighbors(adata, n_neighbors=15, use_rep="X", random_state=seed)
    # flavor="igraph" avoids leidenalg, which is not in the container.
    from sklearn.metrics import adjusted_rand_score, silhouette_score

    scaled_all = np.asarray(adata.X)
    sweep = []
    labels_by_resolution = []
    for r in resolutions:
        key = f"leiden_{r:g}"
        sc.tl.leiden(
            adata,
            resolution=r,
            flavor="igraph",
            n_iterations=2,
            directed=False,
            random_state=seed,
            key_added=key,
        )
        lab = adata.obs[key].to_numpy()
        labels_by_resolution.append(lab)
        n_clusters = len({str(v) for v in lab})

        # Stability as adjusted Rand across seeds. Silhouette is not used to choose: it
        # falls monotonically (0.223 at 5 clusters to 0.079 at 43), so it always picks the coarsest.
        agreements = []
        for extra in (seed + 101, seed + 202):
            sc.tl.leiden(
                adata,
                resolution=r,
                flavor="igraph",
                n_iterations=2,
                directed=False,
                random_state=extra,
                key_added="_stability",
            )
            agreements.append(float(adjusted_rand_score(lab, adata.obs["_stability"].to_numpy())))
        stability = float(np.mean(agreements)) if agreements else None
        # Subsampled because silhouette is quadratic; None when undefined (one cluster).
        score = None
        if 1 < n_clusters < len(lab):
            score = float(
                silhouette_score(
                    scaled_all,
                    lab,
                    sample_size=min(5000, len(lab)),
                    random_state=seed,
                )
            )
        sweep.append(
            {
                "resolution": float(r),
                "n_clusters": n_clusters,
                "silhouette": score,
                "stability": stability,
            }
        )

    # Finest resolution that is stable across seeds; otherwise the most stable one.
    stable = [row for row in sweep if row["stability"] is not None and row["stability"] >= stability_floor]
    how = "stability"
    if stable:
        chosen = max(stable, key=lambda row: row["resolution"])["resolution"]
    else:
        # Reported as its own outcome so a reader knows the floor was never met
        # (published run: best agreement 0.596 against 0.9).
        how = "stability_fallback"
        scored = [row for row in sweep if row["stability"] is not None]
        chosen = max(scored, key=lambda row: row["stability"])["resolution"] if scored else resolutions[0]
    if requested_resolution is not None:
        chosen = float(requested_resolution)
        how = "requested"

    index = min(range(len(resolutions)), key=lambda i: abs(resolutions[i] - chosen))
    resolution = float(resolutions[index])
    labels = labels_by_resolution[index]
    order = sorted({str(v) for v in labels}, key=lambda s: int(s))
    tree = cluster_tree(labels_by_resolution, [float(r) for r in resolutions])

    # Mean z-scored value per cluster per marker, as shown in the heatmap.
    scaled = np.asarray(adata.X)
    matrix = []
    sizes = []
    for cluster in order:
        mask = labels == cluster
        sizes.append(int(mask.sum()))
        matrix.append([float(v) for v in scaled[mask].mean(axis=0)])

    # An all-negative row's argmax is not a positive marker (six such clusters on the
    # published run), so it is flagged rather than dropped; snapshots still need it.
    top_markers = [use_channels[int(np.argmax(row))] for row in matrix]
    top_above_average = [bool(max(row) > 0) for row in matrix]
    return {
        "resolution": resolution,
        "resolution_chosen_by": how,
        "stability_floor": stability_floor,
        "sweep": sweep,
        "tree": tree,
        "arcsinh_cofactor": cofactor if cofactor > 0 else None,
        "arcsinh_cofactors": dict(zip(use_channels, [round(c, 1) for c in cofactors], strict=True)),
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
    """Return the cells nearest each cluster's centroid, as row indices into the full table."""
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
    compartments: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Render each picked cell in its cluster's top marker and the nuclear stain.

    `compartments` (channel to expected compartment) is only recorded in the index.
    """
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
            # Subject cell in thicker yellow so it stands out from its neighbours.
            neighbours = [h for h in hits if int(h) != int(cell)]
            draw_outlines(img, boundaries.geometry.iloc[neighbours], x0, y0)
            draw_outlines(
                img,
                boundaries.geometry.iloc[[int(cell)]],
                x0,
                y0,
                TARGET_MASK_RGB,
                width=2,
            )
            name = f"cell_c{cluster}_{rank}.png"
            img.save(out_dir / name, optimize=True)
            out.append(
                {
                    "cluster": cluster,
                    "file": name,
                    "marker": marker,
                    "marker_compartment": (compartments or {}).get(marker),
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
    ap.add_argument(
        "--markers",
        type=Path,
        help="marker sheet CSV. Supplies channel_role, which identifies the nuclear stain "
        "and the channels to keep out of clustering, plus the background column.",
    )
    ap.add_argument(
        "--nuclear-pattern",
        default=None,
        help="override: name the nuclear stain by substring instead of reading "
        "channel_role == 'dna' from the marker sheet. Needed only for a sheet with no "
        "channel_role column, or to override a wrong one.",
    )
    ap.add_argument("--window", type=int, default=1000, help="crop size in pixels (default: 1000)")
    ap.add_argument("--n-windows", type=int, default=6, help="how many crops (default: 6)")
    ap.add_argument("--cells-per-cluster", type=int, default=5, help="snapshots per cluster (default: 5)")
    ap.add_argument(
        "--resolutions",
        default="0.1,0.2,0.3,0.5,0.8,1.2,1.6,2.0",
        help="Leiden resolutions to sweep, drawn as a tree. Eight is the cap so the tree "
        "stays readable (default: 0.1,0.2,0.3,0.5,0.8,1.2,1.6,2.0)",
    )
    ap.add_argument(
        "--resolution",
        type=float,
        help="pin the resolution used for the heatmap and the cell snapshots. Omit to let "
        "the best mean silhouette across the sweep choose it.",
    )
    ap.add_argument(
        "--arcsinh-cofactor",
        type=float,
        default=0.0,
        help="fixed arcsinh cofactor for every channel. The default of 0 derives one per "
        "channel from the median of its positive values, which is where noise ends.",
    )
    ap.add_argument(
        "--max-cells",
        type=int,
        default=50000,
        help="subsample for clustering, 0 for all cells (default: 50000)",
    )
    ap.add_argument(
        "--stability-floor",
        type=float,
        default=0.9,
        help="minimum adjusted Rand between seeds for a resolution to count as stable; the "
        "finest stable resolution is the one used (default: 0.9)",
    )
    ap.add_argument("--skip-clustering", action="store_true", help="render crops only")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import numpy as np
    import zarr
    from qc_metrics import (
        compartments_by_channel,
        read_column,
        read_marker_cycles,
        sole_image_element,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    element = sole_image_element(args.sdata)
    table = zarr.open_group(str(args.sdata / "tables" / "table"), mode="r")
    channel_names = [str(n) for n in read_column(table["var"]["_index"])]
    centroids = np.asarray(table["obsm"]["spatial"][:])
    boundaries = read_boundaries(args.sdata)

    marker_rows = read_marker_cycles(args.markers) if args.markers else None
    nuclear, nuclear_how = select_nuclear_channels(channel_names, marker_rows, args.nuclear_pattern)
    if not nuclear:
        raise ValueError(
            f"no nuclear channel identified by {nuclear_how}. "
            f"Channels present: {channel_names}. "
            "Set channel_role = 'dna' on the nuclear rows of the marker sheet, or pass "
            "--nuclear-pattern to name the stain by substring."
        )
    nuclear_channel = nuclear[0]
    compartments = compartments_by_channel(marker_rows) if marker_rows else {}
    print(f"[qc_images] nuclear stain: {nuclear_channel} (by {nuclear_how})")

    index: dict[str, Any] = {
        "sample": args.sdata.stem,
        "image_element": element,
        "nuclear_channel": nuclear_channel,
        "nuclear_selected_by": nuclear_how,
        "channel_compartments": compartments,
        "crop_mask_colour": "cyan",
        "mask_colour": "white",
        "target_mask_colour": "yellow",
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
        excluded = clustering_exclusions(nuclear, marker_rows)
        use = [c for c in channel_names if c not in excluded]
        if len(use) < 2:
            raise ValueError(
                f"only {len(use)} channel(s) left to cluster on. Excluded: "
                + ", ".join(f"{k} ({v})" for k, v in sorted(excluded.items()))
                + f". Channels present: {channel_names}"
            )

        x = np.asarray(table["X"][:])
        resolutions = [float(v) for v in args.resolutions.split(",") if v.strip()]
        if len(resolutions) > 8:
            raise ValueError(
                f"{len(resolutions)} resolutions given; the tree is capped at 8 rows so it stays readable"
            )
        clustering = cluster_cells(
            x,
            channel_names,
            use,
            cofactor=args.arcsinh_cofactor,
            resolutions=sorted(resolutions),
            max_cells=args.max_cells,
            requested_resolution=args.resolution,
            stability_floor=args.stability_floor,
        )
        picks = representative_cells(clustering, n_per_cluster=args.cells_per_cluster)
        print(
            "  sweep      : "
            + ", ".join(
                f"{row['resolution']:g}->{row['n_clusters']}"
                + (f" sil={row['silhouette']:.3f}" if row["silhouette"] is not None else "")
                + (f" stab={row['stability']:.3f}" if row["stability"] is not None else "")
                for row in clustering["sweep"]
            )
        )
        print(
            f"  clusters   : {len(clustering['clusters'])} at resolution "
            f"{clustering['resolution']:g} ({clustering['resolution_chosen_by']}) "
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
            compartments=compartments,
        )
        print(f"  snapshots  : {len(index['snapshots'])}")
        index["clustering"] = {k: v for k, v in clustering.items() if not k.startswith("_")}
        index["clustering"]["excluded_channels"] = sorted(excluded)
        index["clustering"]["excluded_channels_why"] = dict(sorted(excluded.items()))

    out_json = args.out_dir / "qc_images.json"
    out_json.write_text(json.dumps(index, indent=2) + "\n")
    print(f"  written    : {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
