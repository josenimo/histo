#!/usr/bin/env python3
"""Merge per-core SpatialData Zarr stores from a dearrayed TMA into one store.

Every core has already been through the whole pipeline independently. This step
only combines the results, so that a slide can be opened as a single object.

Two things make this different from the obvious implementation:

1.  Elements are written one at a time with ``SpatialData.write_element``, not
    accumulated into dicts and written in one ``.write()`` at the end. Images
    read from Zarr are dask-backed, so holding references to them is cheap; it
    is the single terminal write that materialises every core at once and
    exhausts RAM. Writing incrementally lets each core's dask graph be evaluated
    and released before the next one is read. Peak memory becomes one core
    rather than all cores. See ROADMAP.md section 5.

2.  A core that cannot be read is a hard failure. The previous implementation
    caught every exception, printed a warning and carried on, so a slide could
    silently merge 78 of its 80 cores and still exit 0. For unattended runs on
    a colleague's irreplaceable data that is the worst possible behaviour.

Element naming: ``{core_id}__{original_name}``. The separator is a double
underscore because core IDs themselves contain single underscores
(``slide_core001``), and troubleshooting needs an unambiguous split point.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import spatialdata as sd

SEP = "__"

# Element families copied verbatim. Tables are handled separately, because
# their region annotation points at a shapes element whose name this script
# changes, so it has to be rewritten to match.
RASTER_AND_GEOMETRY = ("images", "labels", "shapes", "points")


def core_id_from_path(zarr_path: Path) -> str:
    """Core identity comes from the directory name, e.g. slide_core001.zarr."""
    name = zarr_path.name
    return name[: -len(".zarr")] if name.endswith(".zarr") else name


def retarget_table(table, rename_map: dict[str, str], core: str):
    """Point a table's region annotation at the renamed shapes/labels element.

    A table carries the name of the element it annotates in two places, and
    both have to agree or SpatialData will refuse to link them: the ``region``
    entry of ``uns['spatialdata_attrs']``, and the per-row values of the
    ``region_key`` column in ``.obs``.
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
    if output_zarr.exists():
        # Deliberately not deleting. Inside a Nextflow work directory this
        # cannot happen, and anywhere else an unexpected pre-existing store is
        # far more likely to be someone's data than a stale artefact.
        raise FileExistsError(
            f"{output_zarr} already exists. Refusing to overwrite; remove it yourself "
            f"if that is really what you want."
        )

    # Sorted for determinism: element order in the merged store should not
    # depend on the order Nextflow happened to stage the inputs.
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

    # strict=True: core_ids is derived from input_zarrs, so a length mismatch is
    # impossible unless someone breaks that invariant. Cheap to assert, and a
    # silent truncation here would drop cores from the merge.
    for zarr_path, core in zip(input_zarrs, core_ids, strict=True):
        print(f"[merge] reading {core}", flush=True)
        # No try/except. If a core is unreadable the run must stop.
        sdata = sd.read_zarr(zarr_path)

        rename_map: dict[str, str] = {}
        written: list[str] = []

        for family in RASTER_AND_GEOMETRY:
            for name, element in getattr(sdata, family).items():
                new_name = f"{core}{SEP}{name}"
                rename_map[name] = new_name
                merged[new_name] = element
                # Evaluates and releases this element's dask graph before the
                # next one is touched. This line is the whole point of the file.
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
