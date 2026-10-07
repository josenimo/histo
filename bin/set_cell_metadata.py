#!/usr/bin/env python3
"""Set per-cell provenance columns in a SpatialData table's obs.

sopa writes obs/slide as the image element name, which carries `_backsub` and goes stale
after the TMA merge renames elements. This replaces it with the samplesheet slide name and,
on a TMA, adds obs/core_id. Runs right after `sopa aggregate`, inside AGGREGATE.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# spatialdata is imported inside main() so label_cells is testable without it.


def label_cells(obs, slide: str, core_id: str | None = None):
    """Return obs with slide (and core_id, if given) as categorical columns."""
    import pandas as pd

    if not slide:
        raise ValueError("slide must be a non-empty name")

    obs = obs.copy()
    obs["slide"] = pd.Categorical([slide] * len(obs))
    if core_id:
        obs["core_id"] = pd.Categorical([core_id] * len(obs))
    return obs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sdata", required=True, type=Path, help="SpatialData .zarr store")
    ap.add_argument("--slide", required=True, help="slide name from the samplesheet")
    ap.add_argument("--core-id", help="TMA core ID; omit off-TMA")
    ap.add_argument("--table", default="table", help="table element name (sopa's default)")
    args = ap.parse_args()

    import spatialdata as sd

    sdata = sd.read_zarr(args.sdata)
    if args.table not in sdata.tables:
        raise ValueError(f"no table '{args.table}'. Present: {sorted(sdata.tables)}")

    table = sdata.tables[args.table]
    before = sorted(table.obs["slide"].unique()) if "slide" in table.obs else None
    table.obs = label_cells(table.obs, args.slide, args.core_id)
    # spatialdata refuses overwrite inside its own store; delete-then-write is sopa's own fallback.
    sdata.delete_element_from_disk(args.table)
    sdata.write_element(args.table)

    # Re-read: an in-place overwrite that silently did nothing would otherwise go unnoticed.
    obs = sd.read_zarr(args.sdata).tables[args.table].obs
    if set(obs["slide"]) - {args.slide} or (args.core_id and set(obs["core_id"]) - {args.core_id}):
        raise RuntimeError(f"obs columns did not persist in {args.sdata} :: {args.table}")

    print(f"[set_cell_metadata] {args.sdata} :: {args.table}, {len(obs)} cells")
    print(f"  slide   : {before} -> {args.slide}")
    print(f"  core_id : {args.core_id or '(not a TMA, column not written)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
