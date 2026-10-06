# Longer-term ideas

Not scheduled. Each lists what it would touch, so the cost is visible. Ordered roughly by value
per unit of risk.

## 1. Read `.czi` metadata

A `.czi` carries exposure, channel names, pixel size and tile stage positions. Ashlar reads it
natively.

- Main win: auto-fill `exposure` for backsub instead of transcribing it by hand.
- Fill only what the marker sheet leaves blank; fail on conflict. The sheet stays the source of
  truth.
- Shape: a `CZI_METADATA` module emitting a table, merged with the existing marker sheet
  validation. Channel names could feed `SET_CHANNEL_NAMES` directly.
- Check first: Ashlar's `.czi` support on real files, and whether BaSiCPy needs conversion.

## 2. Coreograph across nuclear channels, to detect lost cores

Cores detach between cycles and the pipeline cannot see it: Coreograph runs once, on one
channel.

- Dearray every `dna` channel (one per cycle, from `channel_role`), match centroids across
  cycles, emit a presence matrix for the QC report.
- Cheap: 1.4 GB and 2.5 minutes per run on a 10-cycle slide, and runs are independent.
- Decide first what a missing core means: drop it, process it with fewer channels, or fail. That
  decides whether this is QC or control flow.

## 3. Imaging QC: autofluorescence and artefacts

Debris, focus, saturation, autofluorescence. Start on the stitched image (one task per sample,
no new plumbing); per-tile checks can come later. Report, do not fail, until thresholds come
from real datasets. Belongs in the Phase 7 QC report.

## 4. Ashlar registration QC

The feature lives on an upstream development branch. Consuming it here is trivial; the cost is
maintaining a merged Ashlar and its container. Options:

- Patch the module to a personal container (`jose_ashlar-1.21.0` exists). Fast, but a patch to
  carry forever.
- Merge and contribute upstream. Slow, and the right answer if generally useful.
- Wait. The residual is one QC input among several.

## 5. Dearray first, then process each core in parallel

Most valuable and most dangerous. Today Ashlar registers about 1000 tiles × 7 cycles in one job;
one failure ruins the slide. Per core it would be about 36 tiles × 7 cycles, giving per-core
parallelism, a better-conditioned registration, and failures limited to one core.

Hard parts:

- **Finding cores without stitching.** A downsampled mosaic from stage positions alone should
  be enough for Coreograph. Without this the idea is circular.
- **Mapping cores to tiles exactly.** An off-by-one silently crops a core.
- **Per-core, per-cycle sub-images with correct stage positions in the OME-XML.** Wrong
  positions give a confidently misregistered image with no error. Prototype first, trust last.
- **Keep BaSiCPy global.** 36 tiles per core is too few for a good profile; estimate per cycle
  on the whole acquisition, apply per core.

Order: (1) check Coreograph finds the same cores on the naive mosaic, else stop; (2) tile
mapping, verified against known cores; (3) one core, one cycle through Ashlar, compared with
the whole-slide result; (4) only then restructure `PREPROCESS_IMAGES`.

Downstream is untouched: core identity, `meta.slide` and `MERGE_SPATIALDATA` already exist.

## Interactions

- Ideas 1, 2 and 5 all need richer marker sheet metadata. Design the new columns once.
- If idea 5 happens, idea 2 becomes "dearray the naive mosaic once per `dna` channel".
- Ideas 2, 3 and 4 all produce QC output; it goes in one report.
