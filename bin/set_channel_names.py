#!/usr/bin/env python3
"""Write marker sheet names onto an image element's channels in a SpatialData store.

Ashlar and Coreograph drop channel names, so sopa would label columns `Channel:0:0`.
Only `images/<element>/zarr.json` metadata changes; must run before aggregation.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# spatialdata is imported inside main() so marker sheet parsing is testable without it.


def read_marker_names(path: Path) -> list[str]:
    """Return marker names sorted by channel_number; gaps are allowed (backsub drops channels)."""
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))

    if not rows:
        raise ValueError(f"{path} has no rows")

    for col in ("channel_number", "marker_name"):
        if col not in rows[0]:
            raise ValueError(f"{path} has no '{col}' column. Columns present: {sorted(rows[0])}")

    rows.sort(key=lambda r: int(r["channel_number"]))
    names = [r["marker_name"].strip() for r in rows]

    if any(not n for n in names):
        blank = [r["channel_number"] for r, n in zip(rows, names, strict=True) if not n]
        raise ValueError(f"{path}: blank marker_name for channel_number(s) {blank}")

    if len(set(names)) != len(names):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise ValueError(
            f"{path}: duplicate marker names {dupes}. Channel names must be unique or "
            f"the feature matrix will have ambiguous columns."
        )

    return names


def channel_labels(sdata_path: Path, element: str) -> list[str]:
    """Read channel labels from `images/<element>/zarr.json` (spatialdata has no getter)."""
    import json

    meta = Path(sdata_path) / "images" / element / "zarr.json"
    if not meta.exists():
        raise FileNotFoundError(
            f"cannot read channel names: {meta} does not exist. Either '{element}' is "
            f"not an image element, or the store layout has changed."
        )

    attrs = json.loads(meta.read_text()).get("attributes", {})
    channels = attrs.get("ome", {}).get("omero", {}).get("channels")
    if channels is None:
        raise ValueError(
            f"{meta} has no attributes.ome.omero.channels. The store layout has "
            f"changed and this script needs updating."
        )
    return [c["label"] for c in channels]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sdata", required=True, type=Path, help="SpatialData .zarr store")
    ap.add_argument("--markers", required=True, type=Path, help="marker sheet CSV")
    ap.add_argument("--element", help="image element name (default: the only one)")
    args = ap.parse_args()

    import spatialdata as sd

    names = read_marker_names(args.markers)
    sdata = sd.read_zarr(args.sdata)

    if args.element:
        element = args.element
        if element not in sdata.images:
            raise ValueError(f"no image element '{element}'. Present: {sorted(sdata.images)}")
    elif len(sdata.images) == 1:
        element = next(iter(sdata.images))
    else:
        raise ValueError(
            f"{len(sdata.images)} image elements present, so --element is required. "
            f"Present: {sorted(sdata.images)}"
        )

    before = channel_labels(args.sdata, element)

    if len(before) != len(names):
        raise ValueError(
            f"channel count mismatch: the image has {len(before)} channels, the marker "
            f"sheet lists {len(names)}.\n"
            f"  image  : {before}\n"
            f"  markers: {names}\n"
            f"If backsub ran, the sheet passed here must be its rewritten markerout, "
            f"not the original: backsub can remove background channels."
        )

    # Unconditional: in-place mutation defeats -resume anyway, and the log then always
    # shows the full mapping. Only metadata is written, so cost is independent of image size.
    sdata.set_channel_names(element, names, write=True)

    after = channel_labels(args.sdata, element)
    if after != names:
        raise RuntimeError(f"channel names did not persist.\n  wanted: {names}\n  on disk: {after}")

    print(f"[set_channel_names] {args.sdata} :: {element}")
    for i, (b, a) in enumerate(zip(before, after, strict=True)):
        print(f"  {i:>3}  {b:<24} -> {a}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
