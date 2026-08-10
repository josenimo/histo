# Roadmap

Status and plan. The reasoning behind the design is in [docs/decisions.md](docs/decisions.md),
longer-term ideas in [docs/future-ideas.md](docs/future-ideas.md), and the blow-by-blow in git
history and the [issues](https://github.com/josenimo/histo/issues).

Priorities, in order: transparency, robustness, troubleshootability.

## Status

| Phase                  | State                                                                     |
| ---------------------- | ------------------------------------------------------------------------- |
| 0. Freeze and diagnose | Done                                                                      |
| 1. Scaffold            | Done — cloned from nf-core/sopa, rebranded, out-of-scope features removed |
| 2. Preprocessing half  | Done — BaSiCPy, Ashlar, backsub, Coreograph                               |
| 3. TMA path            | Done — per-core processing, merged per slide                              |
| 4. Resource profiles   | Done — `size_tiny`/`small`/`medium`/`huge`, `slurm`                       |
| 5. Containers          | Done — 7 images, manifest, pre-staging documented                         |
| 6. Testing             | Done — unit, stub and fixture tiers, CI                                   |
| 7. QC report           | Not started                                                               |
| 8. Release 1.0.0       | Not started                                                               |

Version `0.1.0dev`. Lint: 241 passed, 35 ignored, 5 warnings, 0 failed.

## Verified on real data

- mIF, 3 cycles, 12 channels → 9,855 cells.
- TMA, 2 cycles → 4 cores detected, processed independently, merged to 29,574 cells.
- 10-cycle TMA, with and without background subtraction.
- Tiled segmentation is correct: 9,855 cells as one patch versus 9,896 across six, a 0.4%
  difference. Boundary resolution works, which is the claim the whole downstream design rests on.
- Nothing exceeded 1.7 GB peak RSS across 49 tasks. Ashlar's memory tracks the mosaic's spatial
  extent, not channel count: 889 MB for 2 cycles, 1.3 GB for 10.

## Next

Ordered by how much harder each becomes if deferred.

1. **Marker sheet as a samplesheet column.** Currently one global file broadcast to every
   sample, which is wrong the moment two samples have different channel layouts. Needs
   all-or-nothing validation: every cycle of a sample must name the same sheet. Do this before
   other people depend on the current format, because changing it later is a breaking change
   with an audience.
2. **Aggregation beyond the mean.** sopa reports mean intensity per cell. Quantiles, standard
   deviation and morphology are all reasonable, and would need either a patched sopa module or
   our own aggregation step. The item with scientific rather than engineering value.
3. **Explain `obs/slide`.** It appears on non-TMA runs and nothing in this pipeline writes it.
   Worth understanding before `MERGE_SPATIALDATA` starts writing its own slide identity into
   the same tables.
4. **Phase 7, QC report.** Machine-readable pass or fail for unattended runs: cell count per
   core, saturated-pixel fraction per channel, Ashlar registration residual, fraction of
   patches with zero cells. Thresholds need real datasets behind them.
5. **Phase 8, release.** Tag off `main`, `nf-core pipelines lint --release` first.

## Longer term

Sketched with costs and risks in [docs/future-ideas.md](docs/future-ideas.md).

1. **Read `.czi` metadata** — auto-fill exposure for backsub, and channel names, from the file.
2. **Dearray across every nuclear channel** — detect cores lost between cycles.
3. **Imaging QC** — autofluorescence, artefacts, focus. Merge with Phase 7.
4. **Ashlar registration QC** — lives on an upstream dev branch; revisit when Phase 7 starts.
5. **Dearray first, process each core in parallel** — the largest change here, and the one that
   would most improve Ashlar's reliability. Depends on locating cores from a naive
   stage-position mosaic, without stitching first.

Ideas 1, 2 and 5 all want extra marker sheet columns. Design that schema once, alongside the
already-planned move to a samplesheet column, rather than breaking the format three times.

## Open

- **Duplicate `cycle_number` is accepted, and silently misaligns illumination profiles.** `meta` is
  built from `sample` and `cycle_number` alone, so two samplesheet rows sharing both produce
  identical meta maps. That map is the join key in `preprocess_images/main.nf:48`, so which cycle
  receives which BaSiCPy profile depends on task completion order, and the `groupTuple` sort in the
  same file has the same tie. Seen on a real three-cycle run whose sheet numbered the cycles 1, 2, 2:
  it completed with no guarantee the profiles matched their cycles.
  `assets/schema_input_cycle.json` already promises "sequential and without gaps" in its
  `errorMessage`, but JSON Schema validates rows independently and cannot express a cross-row
  constraint, so that message describes a check that was never written. The check belongs beside
  `validateIlluminationColumns`, which exists for this category and whose comment names this exact
  failure mode. Fix the error message in the same change. Quick, and it converts a silent wrong
  answer into a startup error.
- **backsub's filename suffix leaks into TMA core identity, and from there into the cell table.**
  `conf/modules.config` gives BACKSUB `ext.prefix = { "${meta.id}_backsub" }`, and on the TMA path
  BACKSUB runs before COREOGRAPH, which derives each core's identity from its filename
  (`preprocess_images/main.nf:155`). So with both `use_backsub` and `use_tma` set, `meta.id` becomes
  `{sample}_backsub_core001`, and the suffix propagates into `meta.sample`, the zarr directory name,
  the REPORT filename and the element prefixes `bin/merge_spatialdata.py` writes into the merged
  store. Nothing crashes: the element name and `meta.sample` agree because both come from the same
  filename. The cost is that row identity in the final table depends on whether an optional
  preprocessing step was enabled, so the same slide run with and without backsub yields cores that
  cannot be matched by name. This is the quiet half of the `SET_CHANNEL_NAMES` fix above; making the
  lookup filename-independent does not help, because this is a naming defect rather than a lookup
  one. The suffix is not cosmetic — backsub's input is Ashlar's output, and Nextflow excludes staged
  inputs from output matching, so identical names fail the task with a missing-output error. The fix
  is to stage the input as `path(image, stageAs: 'input/*')` and drop the prefix, which leaves the
  module's own collision guard passing since `$image` renders as `input/{sample}.ome.tif`. Reasoned
  from the module source, not tested. It costs a second patched nf-core module carried through
  `nf-core modules update`, and looks upstreamable, which would remove that cost.
- **`bin/set_channel_names.py` `main()` has no test for element selection.**
  `tests/unit/test_set_channel_names.py` covers marker sheet parsing and `channel_labels()`, but not
  the explicit `--element` path, the single-element fallback, or the "more than one image element"
  error. The pipeline now depends on that fallback, so the least-tested part of the script is the
  part it relies on. Needs a real spatialdata store rather than the JSON fixture `make_store`
  builds, so it is slower than the tests beside it.
- **Resource profiles are estimates** apart from `size_tiny`. Rewrite from `peak_rss` and
  `realtime` in the trace once a genuinely large slide has run.
- **`REPORT` and `FLUO_ANNOTATION` are missing from the three larger size tiers**, so they
  inherit `process_medium` — a one-minute REPORT asked for 36 GB.
- **`PATCH_SEGMENTATION_CELLPOSE` is `process_single` but used 133% CPU.** Belongs in
  `base.config`, since its cost follows `patch_width_pixel` rather than image size.
- **Two inherited nf-test files** still snapshot nf-core/sopa's outputs. Rewrite as property
  assertions rather than regenerating.
- **No real-data test** for the TMA path, background subtraction, or `use_preprocessing = false`.
- **H&E support** is planned; only `ome_tif` mIF input works today.
- **Singularity bind mounts** in `conf/slurm.config` are a commented TODO, unresolved until a
  task fails to find its input.

## Deferred deliberately

- **OME-TIFF channel-name injection.** `tiffcomment -set` patches the header in constant time,
  but a Nextflow task must not mutate its staged input, so it would mean copying the whole
  image. Not worth it for QuPath convenience. Names reach the Zarr instead.
- **Pixel size in the Zarr.** SpatialData has no good model for physical scale, and redefining
  the `global` coordinate system would silently reinterpret `patch_width_pixel` as microns.
  Images stay in pixel units.
- **A real TMA test fixture.** Coreograph is a UNet with scale assumptions, so a cropped TMA
  may fail to detect cores and produce a red test that reflects the fixture, not the pipeline.
- **`groupKey` for the cycle regroup**, and the 4.0.3 → 4.1.0 template bump.
