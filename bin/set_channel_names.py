#!/usr/bin/env python3
"""Give the image channels their marker names, in the SpatialData store.

Ashlar does not write marker names into the OME-XML it produces, and Coreograph
discards them even when backsub has put them there. So by the time sopa reads the
image it finds `Channel` elements with IDs and no names, and falls back to using
the IDs: the expression matrix ends up with columns called `Channel:0:0`. The
quantification is correct and nobody can read it.

Repairing the OME-TIFF was considered and rejected. `tiffcomment -set` patches the
header in place in constant time, which is ideal, but a Nextflow task must not
mutate its staged input -- that input is a symlink into the upstream task's work
directory, and modifying it breaks the immutability `-resume` depends on. Avoiding
that means copying the whole image, which for a 100 GB slide costs more than the
problem is worth. See ROADMAP section 6.

Doing it here instead is free at any image size. Channel names live in exactly one
place in the store: `images/<element>/zarr.json`, about 5 KB, under
`attributes.ome.omero.channels[].label`. No pixel data is touched. The table
inherits the names automatically, because AGGREGATE reads them from the image when
it builds the feature matrix, so this must run before aggregation.

nf-core/mcmicro solves the same problem differently: it never embeds names at all
and passes markers.csv to mcquant as `--channel_names`. sopa has no equivalent
hook, so the names have to be in the object.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# spatialdata is imported inside main() rather than here on purpose. It pulls in
# dask, xarray and zarr and takes seconds to load, and none of it is needed to
# parse a marker sheet -- which is the part with the interesting failure modes and
# the part worth testing without a container.


def read_marker_names(path: Path) -> list[str]:
    """Marker names in channel order.

    Sorted by channel_number rather than trusting file order. Gaps are tolerated:
    when backsub removes background channels its rewritten sheet can leave
    channel_number non-contiguous, and what matters is the relative order of what
    remains, not the absolute values.
    """
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))

    if not rows:
        raise ValueError(f"{path} has no rows")

    for col in ("channel_number", "marker_name"):
        if col not in rows[0]:
            raise ValueError(
                f"{path} has no '{col}' column. Columns present: {sorted(rows[0])}"
            )

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
            raise ValueError(
                f"no image element '{element}'. Present: {sorted(sdata.images)}"
            )
    elif len(sdata.images) == 1:
        element = next(iter(sdata.images))
    else:
        raise ValueError(
            f"{len(sdata.images)} image elements present, so --element is required. "
            f"Present: {sorted(sdata.images)}"
        )

    before = list(sdata.get_channel_names(element))

    if len(before) != len(names):
        raise ValueError(
            f"channel count mismatch: the image has {len(before)} channels, the marker "
            f"sheet lists {len(names)}.\n"
            f"  image  : {before}\n"
            f"  markers: {names}\n"
            f"If backsub ran, the sheet passed here must be its rewritten markerout, "
            f"not the original: backsub can remove background channels."
        )

    # write=True persists to the store. Only the group metadata changes; the arrays
    # are untouched, which is what makes this cheap on a 100 GB image.
    sdata.set_channel_names(element, names, write=True)

    after = list(sd.read_zarr(args.sdata).get_channel_names(element))
    if after != names:
        raise RuntimeError(
            f"channel names did not persist.\n  wanted: {names}\n  on disk: {after}"
        )

    print(f"[set_channel_names] {args.sdata} :: {element}")
    for i, (b, a) in enumerate(zip(before, after, strict=True)):
        print(f"  {i:>3}  {b:<24} -> {a}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
