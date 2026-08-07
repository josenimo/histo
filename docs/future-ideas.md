# Longer-term ideas

Not scheduled. Recorded with what each would touch, so the cost is visible before anyone
starts. Ordered roughly by value per unit of risk.

---

## 1. Read `.czi` metadata

`.czi` becomes the main input format. Ashlar reads it natively, so the samplesheet can point at
`.czi` with little change — but the metadata inside it is worth more than the pixels.

A `.czi` carries exposure time, channel names, pixel size, objective and tile stage positions.
Three of those are things the pipeline currently asks the user to supply by hand.

**Auto-filling exposure for backsub** is the concrete win. `use_backsub` requires `exposure`
and `background` columns, and exposure is a fact about the acquisition that the file already
knows. Transcribing it by hand is exactly the kind of step that goes wrong silently.

The design question is what happens when the file and the sheet disagree. Filling silently
makes the sheet stop being the source of truth, which is the property that makes the pipeline
auditable. Better: **fill only what is absent, and fail loudly on conflict.** The user's sheet
stays authoritative; the file supplies what the user left blank.

Shape: a `CZI_METADATA` module emitting a normalised table, then the same merge-and-validate
logic already used for the effective marker sheet. It also subsumes part of the §6 metadata
stack — `.czi` channel names could feed `SET_CHANNEL_NAMES` directly, so mIF acquisitions would
arrive with real names instead of needing repair.

Watch for: Ashlar's `.czi` support quality on real files, and whether BaSiCPy can read tiles
from `.czi` or needs conversion first. Test both before committing to the format.

---

## 2. Coreograph across nuclear channels, to detect lost cores

Cores detaching between cycles is a routine failure of cyclic IF, and the pipeline currently
cannot see it: Coreograph runs once, on one channel, and whatever it finds becomes the truth.

Running dearray on **every nuclear channel** — one per cycle — and comparing core presence
turns an invisible failure into a table. Which cores were present in cycle 1 and gone by cycle
6, and how much each shrank.

This needs the marker sheet to say which channels are nuclear. That is a small schema addition
(a `nuclear` boolean, or a more general `channel_role`) with a validation rule: at least one
nuclear channel per cycle. Worth having for its own sake — several later features want to know
which channel is DNA, and today that is guessed from `cellpose_channels`.

Cost is low. Coreograph took 1.4 GB and 2.5 minutes on a 10-cycle slide, so N runs is minutes,
and they are independent so they parallelise. The comparison logic is a new script: match
centroids across cycles within a tolerance, emit a presence matrix.

Output is genuinely new information rather than a reformatting of what we already have, which
is a good sign. It also feeds directly into the QC report.

**Open question worth settling first:** if a core is missing in cycle 6, what should happen?
Drop it, process it with fewer channels, or fail? That is a scientific decision, and the answer
determines whether this is a QC report or a control-flow change.

---

## 3. Imaging QC: autofluorescence and artefacts

A module that inspects images for autofluorescence, debris, focus problems and saturation.

The important design constraint is **when it runs and whether it blocks**. Per-tile before
stitching catches acquisition problems earliest and localises them, but multiplies the task
count. On the stitched image it is one task per sample and can measure things tiles cannot,
like whether a whole region is out of focus.

Probably both, eventually. Start with the stitched image because it is one task and needs no
new plumbing.

Default to reporting, not failing. An unattended run on a colleague's data that halts because
one channel looks odd is worse than one that finishes and says so. Add opt-in gating later,
with thresholds that came from real datasets rather than intuition.

Overlaps heavily with Phase 7. Treat them as one piece of work: the QC report is the place this
output belongs.

---

## 4. Ashlar with the QC report from its development branch

The registration QC feature lives on a separate upstream branch and would need merging with
conflicts.

Worth being clear that this is **upstream work, not pipeline work**. From this pipeline's side,
consuming a QC output is trivial — one more declared output and a publish rule. The cost is
entirely in maintaining a merged Ashlar and a container for it.

Three routes, and they differ mostly in who carries the maintenance:

- **Patch the module to a personal container.** Fast, and you already build one
  (`jose_ashlar-1.21.0`). But `nf-core modules patch` means carrying a diff forever and
  re-resolving it on every module update.
- **Merge the branches and contribute upstream.** Slow, uncertain, and the right answer if the
  feature is generally useful — which a registration QC report is.
- **Wait.** Costs nothing, and Ashlar's registration residual is only one input to the QC
  report; cell counts, saturation and patch coverage can land without it.

The registration residual is the single most useful number Ashlar could give us, so this is
worth revisiting when the QC report starts. Not before.

---

## 5. Dearray first, then process each core in parallel

The most valuable and the most dangerous idea here.

Today: illumination correct → stitch the whole slide → dearray → per-core downstream. Ashlar
registers 1000 tiles × 7 cycles in one job, and if it goes wrong the whole slide goes wrong.

Proposed: locate cores first, then illumination correct, stitch and background subtract **each
core independently** — roughly 36 tiles × 7 cycles per core.

The benefits are real and not just about speed:

- **Parallelism** goes from one Ashlar job to one per core.
- **Registration gets easier.** Ashlar's spanning tree over 1000 tiles is where the failures
  have been. A smaller graph is a better-conditioned problem, not merely a faster one.
- **Failure is atomised.** A bad core is re-runnable on its own instead of invalidating a slide.

### What makes it hard

**Coreograph needs a coherent image to find cores, and stitching is what we are trying to
avoid doing globally.** The way out is that locating cores does not need registration —
only placement. A coarse mosaic assembled from tile stage positions alone, downsampled, is
enough to find objects around 1000 px across. So: naive mosaic → Coreograph → core bounding
boxes, with no Ashlar run at all. That is the key move; without it the idea is circular.

**Mapping cores back to tiles must be exact.** Each core's bounding box has to become a set of
tile indices via stage coordinates. Off-by-one in that mapping silently crops a core, and a
cropped core still looks like a plausible image.

**Writing per-core, per-cycle sub-images with valid tile metadata is the real work.** Ashlar
reads stage positions from the OME-XML. Every generated sub-image must carry correct positions
for its subset of tiles, for every cycle. Get this wrong and Ashlar produces a confidently
misregistered image — no error, just wrong data. This is the part to prototype first and trust
last.

**Keep BaSiCPy global.** Illumination profiles are estimated across many tiles; with ~36 per
core the estimate degrades. Compute one profile per cycle from the whole acquisition, then
apply it per core. This differs from the naive restructuring and matters scientifically.

**Cores overlapping shared tiles** is fine — tiles are read-only and can be selected into more
than one core.

### Suggested order

1. Build the naive stage-position mosaic and check Coreograph finds the same cores on it as on
   the current Ashlar output. If that fails, stop; the rest depends on it.
2. Write the tile-selection mapping and verify against known core positions.
3. Write one core's sub-image for one cycle and confirm Ashlar registers it correctly against
   the whole-slide result.
4. Only then restructure `PREPROCESS_IMAGES`.

Each step is independently checkable, which matters because the failure mode is silent.

### What it does not disturb

The downstream half is untouched. Core identity, `meta.slide`, per-core processing and
`MERGE_SPATIALDATA` all exist and work — this changes where cores are created, not what happens
to them afterwards. That is a large part of why the idea is tractable at all.

---

## Interactions

**Ideas 1, 2 and 5 all want richer marker sheet metadata.** Channel roles for idea 2, exposure
for idea 1, and idea 5 benefits from knowing which channel to dearray on. Adding one column at
a time means three breaking changes to the input format. Worth designing the marker sheet once,
with the columns all three need, alongside the already-planned move to a samplesheet column.

**Ideas 2 and 5 both run Coreograph in a new position.** If idea 5 happens, idea 2 becomes
"dearray the naive mosaic once per nuclear channel", which is cheaper than it is today.

**Ideas 2, 3 and 4 all produce QC output.** They should share one report rather than three, and
that report is Phase 7.
