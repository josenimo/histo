#!/usr/bin/env python3
"""Re-tile one exemplar-001 tile into a 2 x 2, 320 px mini fixture that Ashlar can stitch (unused).

Reads two cycles from --source-dir and writes deterministic OME-TIFFs with inherited
metadata to --out-dir. Re-cut tiles align exactly, so registration is barely tested.

    python tools/make_mini_fixture.py \\
        --source-dir /path/to/full/fixture \\
        --out-dir tests/fixture_data
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

OME_NS = "http://www.openmicroscopy.org/Schemas/OME/2016-06"

# Chosen together so Ashlar finds a correlation peak; not exposed as parameters.
TILE = 320
PITCH = 256  # 64 px of overlap, 20 percent


def parse_source(path: Path) -> dict:
    """Read pixel arrays and the acquisition metadata to inherit from the source OME-TIFF."""
    import tifffile

    with tifffile.TiffFile(path) as tif:
        xml = tif.ome_metadata
        arrays = [s.asarray() for s in tif.series]

    images = re.findall(r"<Image\b.*?</Image>", xml, re.S)
    if len(images) != 4:
        raise ValueError(f"{path}: expected 4 tiles (Image elements), found {len(images)}")

    def attr(block: str, name: str) -> str:
        m = re.search(rf'\b{name}="([^"]*)"', block)
        if not m:
            raise ValueError(f"{path}: no {name} in source metadata")
        return m.group(1)

    pixels0 = re.search(r"<Pixels\b[^>]*>", images[0]).group(0)
    return {
        "arrays": arrays,
        "creator": attr(xml, "Creator"),
        "instrument": re.search(r"<Instrument\b.*?</Instrument>", xml, re.S).group(0),
        "acquisition_date": re.search(r"<AcquisitionDate>([^<]+)</AcquisitionDate>", images[0]).group(1),
        "physical_size": attr(pixels0, "PhysicalSizeX"),
        "physical_size_unit": attr(pixels0, "PhysicalSizeXUnit"),
        "physical_size_z": attr(pixels0, "PhysicalSizeZ"),
        "physical_size_z_unit": attr(pixels0, "PhysicalSizeZUnit"),
        "significant_bits": attr(pixels0, "SignificantBits"),
        "dtype": attr(pixels0, "Type"),
        # New tile i inherits source tile i's timing and focus.
        "tiles": [
            {
                "name": attr(img, "Name"),
                "channels": re.findall(r"<Channel\b.*?</Channel>", img, re.S),
                "planes": [
                    {
                        "delta_t": attr(p, "DeltaT"),
                        "delta_t_unit": attr(p, "DeltaTUnit"),
                        "exposure": attr(p, "ExposureTime"),
                        "exposure_unit": attr(p, "ExposureTimeUnit"),
                        "position_z": attr(p, "PositionZ"),
                        "position_z_unit": attr(p, "PositionZUnit"),
                        "the_c": attr(p, "TheC"),
                    }
                    for p in re.findall(r"<Plane\b[^/]*/>", img)
                ],
                "origin": (float(attr(img, "PositionX")), float(attr(img, "PositionY"))),
                "position_unit": attr(img, "PositionXUnit"),
            }
            for img in images
        ],
    }


def densest_window(plane, span: int, step: int = 16) -> tuple[int, int]:
    """Return (y, x) of the `span` square with the most pixels above the 90th percentile."""
    import numpy as np

    thr = np.percentile(plane, 90)
    ii = (plane > thr).astype(np.int64).cumsum(0).cumsum(1)
    best = None
    for y in range(0, plane.shape[0] - span + 1, step):
        for x in range(0, plane.shape[1] - span + 1, step):
            total = ii[y + span - 1, x + span - 1]
            if y:
                total -= ii[y - 1, x + span - 1]
            if x:
                total -= ii[y + span - 1, x - 1]
            if y and x:
                total += ii[y - 1, x - 1]
            if best is None or total > best[0]:
                best = (total, y, x)
    return best[1], best[2]


def cycle_shift(reference, moving) -> tuple[int, int]:
    """Return whole-pixel (dy, dx) putting `moving` onto `reference`, by phase correlation.

    Cycle 2 sits 45 px off in x: 14 percent of a 320 px tile, enough to break stitching.
    """
    import numpy as np

    a = reference.astype(np.float64)
    b = moving.astype(np.float64)
    fa = np.fft.fft2(a - a.mean())
    fb = np.fft.fft2(b - b.mean())
    r = fa * np.conj(fb)
    r /= np.abs(r) + 1e-12
    cc = np.fft.ifft2(r).real
    peak = np.unravel_index(np.argmax(cc), cc.shape)
    dy = peak[0] - (a.shape[0] if peak[0] > a.shape[0] // 2 else 0)
    dx = peak[1] - (a.shape[1] if peak[1] > a.shape[1] // 2 else 0)
    return int(dy), int(dx)


def build_xml(src: dict, size_x: int, size_y: int, n_channels: int, uuid: str) -> str:
    """Build OME-XML with one Image per tile, since Ashlar reads one tile per Image."""
    px, py = src["tiles"][0]["origin"]
    scale = float(src["physical_size"])
    images = []
    for i, tile in enumerate(src["tiles"]):
        gx, gy = i % 2, i // 2
        pos_x = px + gx * PITCH * scale
        pos_y = py + gy * PITCH * scale
        planes = "\n      ".join(
            f'<Plane DeltaT="{p["delta_t"]}" DeltaTUnit="{p["delta_t_unit"]}"'
            f' ExposureTime="{p["exposure"]}" ExposureTimeUnit="{p["exposure_unit"]}"'
            f' PositionX="{pos_x}" PositionXUnit="{tile["position_unit"]}"'
            f' PositionY="{pos_y}" PositionYUnit="{tile["position_unit"]}"'
            f' PositionZ="{p["position_z"]}" PositionZUnit="{p["position_z_unit"]}"'
            f' TheC="{p["the_c"]}" TheT="0" TheZ="0" />'
            for p in tile["planes"]
        )
        channels = "\n      ".join(
            c.replace(f'ID="Channel:{re.search(r"Channel:([0-9]+):", c).group(1)}:', f'ID="Channel:{i}:')
            for c in tile["channels"]
        )
        tiffdata = "".join(
            f'<TiffData FirstC="{c}" FirstT="0" FirstZ="0" IFD="{i * n_channels + c}" PlaneCount="1" />'
            for c in range(n_channels)
        )
        images.append(
            f'''  <Image ID="Image:{i}" Name="{escape(tile["name"])}">
    <AcquisitionDate>{src["acquisition_date"]}</AcquisitionDate>
    <InstrumentRef ID="Instrument:0" />
    <ObjectiveSettings ID="Objective:0" />
    <Pixels BigEndian="false" DimensionOrder="XYCZT" ID="Pixels:{i}" Interleaved="false"'''
            f' PhysicalSizeX="{src["physical_size"]}" PhysicalSizeXUnit="{src["physical_size_unit"]}"'
            f' PhysicalSizeY="{src["physical_size"]}" PhysicalSizeYUnit="{src["physical_size_unit"]}"'
            f' PhysicalSizeZ="{src["physical_size_z"]}" PhysicalSizeZUnit="{src["physical_size_z_unit"]}"'
            f' SignificantBits="{src["significant_bits"]}" SizeC="{n_channels}" SizeT="1"'
            f' SizeX="{size_x}" SizeY="{size_y}" SizeZ="1" Type="{src["dtype"]}">\n'
            f"      {channels}\n      {planes}\n      {tiffdata}</Pixels>\n  </Image>"
        )

    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f'<OME xmlns="{OME_NS}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        f' Creator="{escape(src["creator"])}" UUID="urn:uuid:{uuid}"'
        f' xsi:schemaLocation="{OME_NS} {OME_NS}/ome.xsd">\n'
        f"{src['instrument']}\n" + "\n".join(images) + "\n</OME>"
    )


def write_mini(source: Path, out: Path, y0: int, x0: int, uuid: str) -> dict:
    import numpy as np
    import tifffile

    src = parse_source(source)
    tile0 = src["arrays"][0]
    n_channels = tile0.shape[0]
    span = PITCH + TILE
    region = tile0[:, y0 : y0 + span, x0 : x0 + span]
    if region.shape[1:] != (span, span):
        raise ValueError(f"region {region.shape[1:]} is not {span}x{span}; crop origin is off the tile")

    xml = build_xml(src, TILE, TILE, n_channels, uuid)
    with tifffile.TiffWriter(out, ome=False, bigtiff=False) as tif:
        for i in range(4):
            gx, gy = i % 2, i // 2
            sub = region[:, gy * PITCH : gy * PITCH + TILE, gx * PITCH : gx * PITCH + TILE]
            for c in range(n_channels):
                tif.write(
                    np.ascontiguousarray(sub[c]),
                    # Bytes: tifffile rejects the non-ASCII "\u00b5m" in a str description.
                    description=xml.encode("utf-8") if (i == 0 and c == 0) else None,
                    compression="deflate",
                    metadata=None,
                    contiguous=False,
                )
    return {"span": span, "tile": TILE, "pitch": PITCH, "channels": n_channels}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-dir", required=True, type=Path, help="directory holding the full-size fixture")
    ap.add_argument("--out-dir", required=True, type=Path, help="where to write the mini fixture")
    args = ap.parse_args()

    import tifffile

    cycles = [
        ("exemplar-001-cycle-06.ome.tiff", "exemplar-001-mini-cycle-01.ome.tiff"),
        ("exemplar-001-cycle-07.ome.tiff", "exemplar-001-mini-cycle-02.ome.tiff"),
    ]
    for name, _ in cycles:
        if not (args.source_dir / name).exists():
            print(f"missing source image: {args.source_dir / name}", file=sys.stderr)
            return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # Crop origin is chosen on the first cycle; later cycles follow the tissue.
    with tifffile.TiffFile(args.source_dir / cycles[0][0]) as tif:
        nuclear = tif.series[0].asarray()[0]
    y0, x0 = densest_window(nuclear, PITCH + TILE)
    print(f"crop origin y={y0} x={x0}, chosen for nuclear signal density")

    origins = [(y0, x0)]
    for src_name, _ in cycles[1:]:
        with tifffile.TiffFile(args.source_dir / src_name) as tif:
            later = tif.series[0].asarray()[0]
        dy, dx = cycle_shift(nuclear, later)
        oy, ox = y0 - dy, x0 - dx
        span = PITCH + TILE
        if not (0 <= oy <= later.shape[0] - span and 0 <= ox <= later.shape[1] - span):
            raise ValueError(
                f"{src_name}: the tissue matching the chosen crop sits at y={oy} x={ox}, "
                f"which is off the tile. The cycles have drifted further than a {span} px "
                "window can follow; pick a crop nearer the tile centre."
            )
        origins.append((oy, ox))
        print(f"  {src_name}: cycle drift dy={dy} dx={dx} px, cropping at y={oy} x={ox}")

    total = 0
    for i, (src_name, out_name) in enumerate(cycles):
        out = args.out_dir / out_name
        y0, x0 = origins[i]
        # Fixed UUIDs keep the output byte-identical across runs.
        info = write_mini(
            args.source_dir / src_name, out, y0, x0, f"00000000-0000-4000-8000-00000000000{i + 1}"
        )
        total += out.stat().st_size
        print(f"  {out_name}  {out.stat().st_size / 1e6:.2f} MB")

    print(
        f"{info['tile']} px tiles, pitch {info['pitch']}, overlap {info['tile'] - info['pitch']} px, "
        f"mosaic about {info['span']} x {info['span']} px, {total / 1e6:.2f} MB total"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
