#!/usr/bin/env python3
"""Cut a small fixture out of the full-size exemplar001 fixture.

**Not currently used.** Real-pixel testing happens as two manual runs on the cluster
before a release, not in CI, so nothing here needs a committed fixture and none is
committed. This is kept because the analysis behind it was expensive and the
conclusion is worth not re-deriving: if CI ever gains somewhere to run containers,
this produces a 2.7 MB fixture that Ashlar reads and stitches, verified.

Why CI was ruled out, in the numbers that decided it: the pipeline's images are
about 8.8 GB on disk for the mIF path and 14.7 GB with Coreograph, against roughly
14 GB of free space on a GitHub-hosted runner and a 10 GB cache quota. Every image
would be re-pulled per run. That is not a fixture problem and a smaller fixture does
not solve it.

Shrinking it is not a crop. The tiles are 1280 x 1080 with stage positions 817 um
apart, which at 0.65 um/px is a pitch of 1257 px and therefore an overlap of only
23 px. Crop a tile below 1257 px and the overlap goes negative, leaving Ashlar
nothing to register on. Compression does not help either: the source is entirely
uncompressed and deflate returns 1.18x, because sensor noise does not compress.

So this re-tiles instead. It takes one real tile, cuts a square region out of it,
and re-cuts that region into a 2 x 2 grid with an overlap we choose, writing stage
positions to match. The pixels are real, the cells are real, the overlap regions
contain the same real cells seen twice, and both cycles are cut from the same stage
region so the cross-cycle comparison is real too.

What this is a weaker test of, stated plainly: registration. Re-cutting one tile
means the correct alignment is exactly the pitch, with no stage-position error, no
illumination falloff across a tile boundary and no real misregistration to recover
from. It exercises BaSiCPy and Ashlar and asserts the wiring and the outputs are
consistent; it does not prove Ashlar can rescue a badly positioned mosaic. The
full-size fixture still does that, and still exists.

Metadata is lifted from the source rather than invented: instrument, objective,
acquisition date, channel wavelengths, exposure times, DeltaT, PositionZ, physical
pixel size and the position units all carry through unchanged. Only the image
dimensions and the X/Y stage positions differ, because those are what re-tiling
changes. Channel names are absent in the source and stay absent, since
SET_CHANNEL_NAMES sets them from the marker sheet.

    python tools/make_mini_fixture.py \\
        --source-dir /path/to/full/fixture \\
        --out-dir tests/fixture_data

Deterministic: same inputs, same bytes out, verified across runs. That mattered when
the output was going to be committed, and still matters if it ever is again: a
committed binary that changes whenever anyone re-derives it is what makes a
repository grow without bound.

Verified when written, on 2026-08-26: Ashlar reads the output and stitches it to
exactly the predicted 576 x 576 mosaic with no gaps; the file has the same
four-Image structure Bio-Formats wrote; adjacent tiles' overlap regions are
pixel-identical; the two cycles correlate at 0.992 after the crop follows the
tissue rather than the stage coordinates.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

OME_NS = "http://www.openmicroscopy.org/Schemas/OME/2016-06"

# Deliberately not a parameter. The overlap has to clear whatever Ashlar needs to
# find a correlation peak, and the tile has to be big enough that a patch grid over
# the mosaic is more than one patch. These two were chosen together; exposing them
# would invite a combination that produces a fixture nothing can stitch.
TILE = 320
PITCH = 256  # 64 px of overlap, 20 percent


def parse_source(path: Path) -> dict:
    """Everything the new file should inherit, read off the source OME-XML.

    Read rather than hardcoded so that the mini fixture stays a faithful derivative:
    if the source is ever replaced, the acquisition metadata follows it instead of
    silently describing the old one.
    """
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
        # One list entry per source tile. The new grid has the same number of tiles,
        # so tile i inherits tile i's timing and focus rather than a single value
        # copied four times, which would flatten a real per-tile spread.
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
    """Top-left of the `span` square holding the most bright pixels.

    Chosen on signal rather than at random because a fixture cut from empty slide
    segments nothing, and a cell count of zero is a baseline that cannot regress.
    A summed-area table keeps this exhaustive rather than sampled.
    """
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
    """Whole-pixel (dy, dx) putting `moving` onto `reference`, by phase correlation.

    The stage nominally returns to the same coordinates each cycle and does not
    quite: on this source the second cycle sits 45 px away in x. Over a 1280 px tile
    that is 3.5 percent and Ashlar absorbs it. Over a 320 px tile it is 14 percent,
    so cropping both cycles at the same coordinates would hand the mini fixture a
    relatively four times worse misregistration than the full one has, and a fixture
    that might fail to stitch is a red test about the fixture rather than about the
    pipeline.

    So the crop follows the tissue instead of the coordinates, and the residual
    cross-cycle shift is close to zero by construction. That is a real property of
    the source being removed, and it is removed deliberately: this fixture exists to
    check that inputs, outputs and wiring stay consistent, not to prove Ashlar can
    recover a bad mosaic. The full-size fixture keeps the shift and still tests it.
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
    """OME-XML for the new grid, structured exactly like the source.

    Written out rather than delegated to tifffile's metadata= argument, which emits
    a single Image with a Q axis for a stacked array. Ashlar reads one tile per
    Image, so that shape would present a four-tile mosaic as one four-plane image
    and stitch nothing.
    """
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
                    # Encoded rather than passed as str: the unit is "\u00b5m" and
                    # tifffile refuses non-ASCII in a TIFF string, while Bio-Formats
                    # writes it as raw UTF-8 in the source. Bytes reproduce that
                    # exactly, which an XML entity would not.
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

    # The crop origin is chosen once, on the first cycle, and reused for the second.
    # Both cycles image the same stage positions, so the same origin is the same
    # tissue -- which is what makes the cross-cycle nuclear comparison meaningful
    # rather than a comparison of two unrelated fields.
    with tifffile.TiffFile(args.source_dir / cycles[0][0]) as tif:
        nuclear = tif.series[0].asarray()[0]
    y0, x0 = densest_window(nuclear, PITCH + TILE)
    print(f"crop origin y={y0} x={x0}, chosen for nuclear signal density")

    # Each later cycle is cropped where its tissue is, not where its coordinates say.
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
        # Fixed UUIDs: the output must be byte-identical across runs, or committing
        # it means committing a new blob every time anyone re-derives it.
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
