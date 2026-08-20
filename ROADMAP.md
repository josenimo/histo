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
| 7. QC report           | Metrics, images and report wired in; thresholds still need real datasets  |
| 8. Release 1.0.0       | Not started                                                               |

Version `0.1.0dev`. Lint: 262 passed, 38 ignored, 6 warnings, 0 failed.

## Verified on real data

- mIF, 3 cycles, 12 channels → 9,855 cells.
- TMA, 2 cycles → 4 cores detected, processed independently, merged to 29,574 cells.
- 10-cycle TMA, with and without background subtraction.
- Tiled segmentation is correct: 9,855 cells as one patch versus 9,896 across six, a 0.4%
  difference. Boundary resolution works, which is the claim the whole downstream design rests on.
- Nothing exceeded 1.7 GB peak RSS across 49 tasks. Ashlar's memory tracks the mosaic's spatial
  extent, not channel count: 889 MB for 2 cycles, 1.3 GB for 10.
- WSI, 3 cycles, 15 channels (5 of them background), 21,798 x 11,295 px, `use_backsub = true`
  → 142,493 cells in 72 patches. Every QC metric and every threshold in Phase 7 was calibrated
  against this one run, which is the single biggest caveat on all of them. Its numbers are quoted
  throughout the QC code and tests deliberately, so a regression disagrees with something that
  actually happened rather than with an invented expectation. Peak RSS was 8.7 GB in BASICPY, which
  contradicts the 1.7 GB line above -- that was a smaller run, and the line is now stale as a
  general claim.

## Next

Ordered by how much harder each becomes if deferred.

1. **Aggregation beyond the mean.** sopa reports mean intensity per cell. Quantiles, standard
   deviation and morphology are all reasonable, and would need either a patched sopa module or
   our own aggregation step. The item with scientific rather than engineering value.
2. **Explain `obs/slide`.** It appears on non-TMA runs and nothing in this pipeline writes it.
   Worth understanding before `MERGE_SPATIALDATA` starts writing its own slide identity into
   the same tables.
3. **Phase 7's remaining half: the pass-or-fail gate.** The metrics, the images and the report are
   in and published to `<outdir>/qc`; `{sample}_qc.json` is the machine-readable contract a gate
   would read. What is missing is the gate itself, and it is blocked on data rather than on code:
   every threshold worth setting needs several slides behind it, and the one slide available says
   different things than a second one might. Deliberately no thresholds and no exit code were
   written, so that a guess did not end up baked into the pipeline's verdict. Two of the four
   metrics originally listed here are still absent: Ashlar's registration residual, which exists
   only in its stderr (see Longer term), and run-level resource QC, which is structurally blocked
   (see Open).
4. **Phase 8, release.** Tag off `main`, `nf-core pipelines lint --release` first.

## Longer term

Sketched with costs and risks in [docs/future-ideas.md](docs/future-ideas.md).

1. **Read `.czi` metadata** — auto-fill exposure for backsub, and channel names, from the file.
2. **Dearray across every nuclear channel** — detect cores lost between cycles.
3. **Imaging QC** — autofluorescence, artefacts, focus. Merge with Phase 7.
4. **Ashlar registration QC** — lives on an upstream dev branch. Phase 7 has now started and this
   is the one metric it could not supply: the residual exists only in Ashlar's stderr, which
   nothing captures or publishes, so it needs a module change before QC can report it.
5. **Dearray first, process each core in parallel** — the largest change here, and the one that
   would most improve Ashlar's reliability. Depends on locating cores from a naive
   stage-position mosaic, without stitching first.

Ideas 1, 2 and 5 all want extra marker sheet columns. Design that schema once, alongside the
already-planned move to a samplesheet column, rather than breaking the format three times.

## Open

- **Leiden clusters are not reproducible on the one slide we have, and that is a finding rather
  than a bug.** Across eight resolutions from 0.1 to 2.0, the best agreement between partitions from
  different random seeds was 0.596 adjusted Rand, against the 0.9 floor the QC step asks for. So no
  resolution on that slide produces a partition worth calling cell types, and the report says as
  much instead of presenting the clusters as phenotypes. Worth re-checking on a second slide before
  concluding it is a property of the data rather than of this one sample. If it holds, the honest
  move is to present clusters only as a summary of staining, or to drop them for a supervised
  gating step against known markers.
- **Silhouette was tried and rejected for choosing a Leiden resolution; do not reach for it again.**
  It falls monotonically as resolution rises -- 0.223 at five clusters down to 0.079 at forty-three
  on the measured run -- so maximising it always returns the coarsest option on offer, and it chose
  five clusters. It is still computed and reported for reference. Selection uses seed-to-seed
  stability instead, which is not monotone and ranked resolution 0.1 _worst_, the opposite verdict.
  Both numbers are in the report's sweep table.
- **The marker sheet now says which channel is a nuclear stain, but the QC scripts do not read it
  yet.** `channel_role` is a required column and `dna` is one of its values, validated to appear in
  every cycle. The cross-cycle photobleaching check and the cluster snapshots still find the
  nuclear channel by matching the marker name against `--nuclear-pattern`, defaulting to `DAPI`,
  which works on every dataset seen so far and goes quiet on a Hoechst-stained one. Replacing the
  pattern with the column is the next branch, and touches `bin/qc_metrics.py`, `bin/qc_images.py`
  and their tests. One wrinkle to handle there: backsub drops rows whose `remove` column is set, so
  a sheet marking a `dna` channel for removal validates on the way in and has no `dna` channel left
  in the `markerout` the QC step reads.
- **`sopa report` and the new QC report now overlap, and one of them should probably go.** sopa's
  `{sample}_analysis_summary.html` draws cell count, an area histogram, channel names, per-cell
  intensity distributions and a UMAP; the QC report covers all of that except the UMAP, in a page
  that is self-contained and backed by a machine-readable JSON. Keeping both means every run pays
  for REPORT and publishes two HTML files that disagree in style and overlap in content. Dropping
  REPORT would also remove the `.sopa_cache` deletion that forces QC and MERGE_SPATIALDATA to chain
  off it. Decide before release; the only thing genuinely lost is the UMAP.
- **scanpy and igraph are uncited.** Both arrive as transitive sopa dependencies rather than as new
  tools, so `CITATIONS.md` is not strictly wrong, but the QC report's clustering is scanpy's Leiden
  via igraph and that is a scientific method presented in output a reader may act on. Cite both, or
  drop the clustering, before tagging 1.0.0.
- **Booleans still cannot be set on the command line, but the attempt now fails instead of
  inverting.** Two separate mechanisms, and the roadmap previously described only one of them.
  `--use_qc=false` arrives as the string `"false"`, which is truthy in Groovy. `--use_qc false` is
  different and worse: Nextflow reads the flag on its own, sets it to boolean `true`, and discards
  the `false` entirely, so it reaches neither `params` nor the positional args and the run
  explicitly enables what it was asked to skip. Both are rejected at startup now.
  **Coercing the value, which this entry used to propose, is not possible.** `params` is a
  `ScriptBinding$ParamsMap` and ignores writes to a key that is already set: `params.use_qc = false`
  and `params.putAll([use_qc: false])` both return without error and change nothing, verified on
  Nextflow 26.04.6. Making the spaced form work would need a change in Nextflow, since the value is
  destroyed before any pipeline code runs. A params file remains the way to set a boolean, and a
  bare flag remains the way to switch one on.
- **Run-level resource QC is deferred, and the reason is structural.** Failed and retried task
  counts and peak RSS per task all live in `pipeline_info/execution_trace_*.txt`, which Nextflow
  only finalises when the run ends — so no process inside the DAG can read its own run's trace, and
  the per-sample QC step cannot produce these numbers. It needs either a `workflow.onComplete` hook
  or a post-run step, and neither is worth building until the pass/fail gate exists to consume it.
  A working parser was written and removed in the same branch rather than left unwired; the trace
  columns are `status`, `attempt` and `peak_rss`, and sizes arrive as `5.1 GB` or as `-` when there
  is no reading at all, which is every row on macOS without a container engine. Worth having: the
  published WSI run peaked at 8.7 GB in BASICPY, and `TO_SPATIALDATA` reported exactly 8.00 GiB,
  which looks like a ceiling rather than a measurement.
- **`min_area_pixels2 = null` filters nothing, and the reason is now known.** No cluster run was
  needed after all; sopa's source answers it. `sopa/segmentation/methods/_cellpose.py` does
  `if min_area is None: min_area = (diameter / 2) ** 2`, so the derivation `nextflow.config`
  described is real, but it lives in the Python API. The CLI this pipeline calls declares
  `min_area: int = typer.Option(0, ...)` in `sopa/cli/segmentation.py`, so `argsCLI()` skipping the
  null means no `--min-area` is passed and typer supplies 0 rather than the None that would trigger
  the derivation. Filtering is therefore off, which matches the published WSI run: smallest cell
  4.3 px², 1% under 48.6 px², against the ~306 px² that `(35/2)²` implies. Neither of the two
  hypotheses recorded here was right; the comment was describing a real derivation on a code path
  this pipeline does not use. The comment now says so. **Open decision:** whether to pass
  `(cellpose_diameter / 2)²` explicitly when the parameter is null, which would reproduce sopa's
  documented intent in one line of `extractSubArgs`, or to keep filtering off by default. That
  changes segmentation results, so it is a scientific call rather than a fix. Note also that
  `sopa/cli/resolve.py` takes a `min_area` in **microns²** while the segmentation CLI takes
  pixels²; this pipeline only routes to the latter, so there is no unit mismatch today, but there
  would be if the parameter were ever wired to resolve.

- **A misspelt parameter does not fail the run.** `pipeline_info/params_*.json` from the published
  run records both `use_use_tma_dearray` and `use_tma_dearray`, with `validate_params = true`. The
  typo was accepted and silently ignored, so a run configured with `use_use_tma_dearray = true`
  would quietly do the opposite of what was asked. nf-core's schema validation can reject unknown
  parameters; find out why it did not here.
- **backsub's filename suffix does not leak into core identity. The entry that said it did was
  wrong.** Recorded here rather than deleted, because it was reasoned from module source without
  being tested and then believed for a fortnight. The claim was that `ext.prefix = { "${meta.id}_backsub" }`
  reaches core IDs, `meta.sample`, the zarr directory name, the REPORT filename and the merged
  element prefixes. It reaches none of them. COREOGRAPH is patched to name cores
  `${prefix}_core001` from `ext.prefix = { "${meta.id}" }`, set explicitly in `conf/modules.config`,
  and BACKSUB passes `meta` through unchanged, so `meta.id` is still the slide when Coreograph runs.
  That patch (98a74a0, 6 August) predates the entry (e954f35, 10 August), so this was never true.
  Verified on stub runs with `use_backsub` both with and without `use_tma_dearray`: `_backsub`
  appears on backsub's own two published files and nowhere else, while every downstream name is
  `{slide}_core001` or `{slide}`. The prefix is still required for the reason `conf/modules.config`
  gives, that without it backsub's output would collide with its staged input. No module patch, no
  upstream PR. The one place the suffix does survive is the image element name inside the zarr, since
  `sopa convert` names elements after the file it converted, and `SET_CHANNEL_NAMES` already handles
  that by taking the sole image element rather than addressing it by name.

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
