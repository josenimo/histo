# Decisions

Why the pipeline is built the way it is. Each entry settles a question that would otherwise
be asked again.

## Architecture

**Two upstream projects, one handoff.** Preprocessing from nf-core/mcmicro, segmentation onward
from nf-core/sopa, meeting at a stitched OME-TIFF. sopa tiles segmentation, so it is size
independent; with 5–100 GB inputs that outranks everything else.

**Cloned, not forked.** sopa was imported at `c2b4e5f` with fresh history, verified
byte-identical by tree hash before any change.

**Not an nf-core pipeline**, but follows its conventions. Template divergences are listed in
`.nf-core.yml`.

## The TMA path

**Merge at the very end.** Each core runs the whole downstream half alone. Many small dense
objects segment better than one large sparse one, and per-core QC survives.

**`MERGE_SPATIALDATA` writes one element at a time**, so peak memory is one core, not all of
them (614 MB for four cores).

**An unreadable core is a hard failure.** The predecessor warned and continued, so a slide
could merge 78 of 80 cores and exit 0.

**Elements are named `{core_id}__{original}`**, skipping the prefix if already present. The
double underscore is because core IDs contain single ones.

## Channel names

Ashlar writes no marker names, backsub writes them, Coreograph drops them. sopa then reads the
OME channel IDs, giving columns like `Channel:0:0`.

**Fixed in the Zarr after conversion.** `SET_CHANNEL_NAMES` writes them from the marker sheet
into about 5 KB of group metadata, free at any image size. `AGGREGATE` inherits them.

**The OME-TIFF is left alone.** A task must not mutate its staged input (a symlink into the
upstream work directory, which `-resume` relies on), so it would mean copying the whole image.

**Check the property, not a proxy.** The old guard grepped sopa's log for a message that only
fires when no names are found. It never fired, since sopa found the IDs.

## Pixel size

Not in the Zarr. SpatialData's option, an extra coordinate system, is a poor fit, and
redefining `global` would silently make `patch_width_pixel` and `min_area_pixels2` microns.
Images stay in pixels; Ashlar keeps `PhysicalSizeX` in the OME-TIFF.

## Parameters

**`patch_width_pixel` is not computed for you.** It changes results at patch boundaries, so an
automatic value would make the same slide segment differently on different hardware. See
[usage.md](usage.md).

**Size profiles are one file**, `conf/sizes.config`, with its own `profiles` scope.

**Tiled segmentation is not scaled by size profile.** Its cost follows `patch_width_pixel`. A
larger slide means more tasks, not bigger ones.

## Containers

**Nothing is pulled at run time.** A pull failing hours in wastes the run and the queue slot.
`containers.tsv` is kept current by a pre-commit hook; see [containers.md](containers.md).

**The cache check computes Nextflow's exact filename.** Matching on tool and version once
reported an image as cached under another URI's name, and Nextflow still went to the network.

## Testing

**Properties, not checksums.** Cellpose output shifts with version and hardware. Channel names,
element names and patch counts cannot drift; cell count gets ±2%.

**A stub run cannot detect an incomplete commit.** Nextflow reads the working tree, not what
git recorded. `tools/clone_check.sh` runs from a fresh clone.

## Recurring lessons

- Validation never watched to fail is not validation. An `assert` inside a channel operator is
  swallowed; use `error()`.
- Error messages often point away from the cause. `nextflow config . -profile X` quickly
  separates a profile that is not loading from a broken pipeline.
- Version-proofing one side of a coupling is half a job. The Coreograph patch handled both
  versions' extensions; the parser of its filenames did not, and `.ome` leaked into core IDs.
