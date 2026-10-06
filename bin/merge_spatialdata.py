#!/usr/bin/env python3
"""Merge per-core SpatialData Zarr stores from a dearrayed TMA into one store.

Elements are renamed ``{core_id}__{name}`` (core IDs contain single underscores) and
written one at a time so peak memory is one core. An unreadable core fails the run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# spatialdata is imported inside merge() so the pure logic is unit-testable without it.

SEP = "__"

# Tables are handled separately: their region annotation must follow the rename.
RASTER_AND_GEOMETRY = ("images", "labels", "shapes", "points")


def core_id_from_path(zarr_path: Path) -> str:
    """Return the core ID from the store directory name, e.g. slide_core001.zarr."""
    name = zarr_path.name
    return name[: -len(".zarr")] if name.endswith(".zarr") else name


def retarget_table(table, rename_map: dict[str, str], core: str):
    """Rewrite a table's region in uns['spatialdata_attrs'] and its obs region_key column.

    Both must agree or SpatialData refuses to link the table.
    """
    import pandas as pd

    attrs = table.uns.get("spatialdata_attrs")
    if not attrs:
        raise ValueError(
            f"[{core}] table has no uns['spatialdata_attrs']; it was not written "
            f"by SpatialData and cannot be relinked safely."
        )

    region = attrs.get("region")
    if isinstance(region, str):
        targets = [region]
    elif isinstance(region, list):
        targets = list(region)
    else:
        raise ValueError(f"[{core}] unexpected region annotation type: {type(region)!r}")

    missing = [t for t in targets if t not in rename_map]
    if missing:
        raise ValueError(
            f"[{core}] table annotates element(s) {missing}, which were not found "
            f"among this core's shapes/labels. Known: {sorted(rename_map)}"
        )

    new_targets = [rename_map[t] for t in targets]
    attrs["region"] = new_targets[0] if isinstance(region, str) else new_targets

    region_key = attrs.get("region_key")
    if region_key and region_key in table.obs:
        table.obs[region_key] = pd.Categorical([rename_map[str(v)] for v in table.obs[region_key]])

    return table


def merge(output_zarr: Path, input_zarrs: list[Path]) -> dict:
    import spatialdata as sd

    if output_zarr.exists():
        # Never delete: outside a work directory it is more likely someone's data.
        raise FileExistsError(
            f"{output_zarr} already exists. Refusing to overwrite; remove it yourself "
            f"if that is really what you want."
        )

    # Staging order is not deterministic.
    input_zarrs = sorted(input_zarrs, key=lambda p: p.name)

    core_ids = [core_id_from_path(p) for p in input_zarrs]
    duplicates = {c for c in core_ids if core_ids.count(c) > 1}
    if duplicates:
        raise ValueError(
            f"Duplicate core IDs among inputs: {sorted(duplicates)}. Core IDs become "
            f"element name prefixes and must be unique within a slide."
        )

    merged = sd.SpatialData()
    merged.write(output_zarr)
    print(f"[merge] initialised empty store at {output_zarr}", flush=True)

    manifest: dict[str, dict] = {}

    for zarr_path, core in zip(input_zarrs, core_ids, strict=True):
        print(f"[merge] reading {core}", flush=True)
        # No try/except: an unreadable core must stop the run.
        sdata = sd.read_zarr(zarr_path)

        rename_map: dict[str, str] = {}
        written: list[str] = []

        for family in RASTER_AND_GEOMETRY:
            for name, element in getattr(sdata, family).items():
                # sopa names the image after the sample (= core ID); avoid core__core.
                new_name = name if name == core else f"{core}{SEP}{name}"
                rename_map[name] = new_name
                merged[new_name] = element
                # Materialises and releases this element before the next; keeps peak RAM to one core.
                merged.write_element(new_name)
                written.append(new_name)
                print(f"[merge]   wrote {family}/{new_name}", flush=True)

        for name, table in sdata.tables.items():
            new_name = f"{core}{SEP}{name}"
            merged[new_name] = retarget_table(table.copy(), rename_map, core)
            merged.write_element(new_name)
            written.append(new_name)
            print(f"[merge]   wrote tables/{new_name}", flush=True)

        if not written:
            raise ValueError(f"[{core}] contributed no elements; the store looks empty.")

        manifest[core] = {"source": str(zarr_path), "elements": written}

    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", required=True, type=Path, help="merged .zarr to create")
    ap.add_argument("--manifest", type=Path, help="write a JSON record of what was merged")
    ap.add_argument("inputs", nargs="+", type=Path, help="per-core .zarr stores")
    args = ap.parse_args()

    manifest = merge(args.output, args.inputs)

    if args.manifest:
        args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True))

    n_elements = sum(len(v["elements"]) for v in manifest.values())
    print(f"[merge] done: {len(manifest)} cores, {n_elements} elements -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
