# Roadmap

Status and plan. **This file is the tracker.** GitHub Issues is enabled but empty and unused, so
anything open lives here, under Next, Longer term or Open. The reasoning behind the design is in
[docs/decisions.md](docs/decisions.md), longer-term ideas in
[docs/future-ideas.md](docs/future-ideas.md), and the blow-by-blow in git history.

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

Version `0.1.0dev`. Lint: 263 passed, 42 ignored, 6 warnings, 0 failed.

## Verified on real data

- mIF, 3 cycles, 12 channels → 9,855 cells.
- TMA, 2 cycles → 4 cores detected, processed independently, merged to 29,574 cells.
- 10-cycle TMA, with and without background subtraction.
- Tiled segmentation is correct: 9,855 cells as one patch versus 9,896 across six, a 0.4%
  difference. Boundary resolution works, which is the claim the whole downstream design rests on.
- WSI, 3 cycles, 15 channels (5 of them background), 21,798 x 11,295 px, `use_backsub = true`
  → 142,493 cells in 72 patches. Every QC metric and every threshold in Phase 7 was calibrated
  against this one run, which is the single biggest caveat on all of them. Its numbers are quoted
  throughout the QC code and tests deliberately, so a regression disagrees with something that
  actually happened rather than with an invented expectation.

### Memory

Two measurements, and the larger one is the one to plan against.

- **8.7 GB peak RSS in BASICPY** on the WSI run above. `TO_SPATIALDATA` reported exactly 8.00 GiB,
  which looks like a ceiling rather than a measurement, so treat it as unmeasured.
- **1.7 GB across 49 tasks** on the smaller mIF and TMA runs. Ashlar's memory tracked the mosaic's
  spatial extent rather than channel count there: 889 MB for 2 cycles, 1.3 GB for 10.

The two are not in conflict once the slide size is attached to each, which the earlier version of
this section did not do: it asserted the 1.7 GB figure as a general claim and then contradicted it
four lines later. Resource profiles are still estimates apart from `size_tiny`, and rewriting them
wants `peak_rss` and `realtime` from a trace on a genuinely large slide.

## Next

Ordered by how much harder each becomes if deferred.

1. **Aggregation beyond the mean.** sopa reports mean intensity per cell. Quantiles, standard
   deviation and morphology are all reasonable, and would need either a patched sopa module or
   our own aggregation step. The item with scientific rather than engineering value, and now also
   the gate on two others: post-aggregation cell filtering has nothing to filter on until these
   metrics exist, and the segmentation-time filter stays off until then (see Known limitations).

2. **Post-aggregation cell filtering.** The place to reject degenerate cells, once there are
   per-cell metrics worth thresholding. Ordered after item 1 deliberately. This is where filtering
   belongs rather than in the segmentation call, because it is reversible, inspectable in the QC
   report, and does not change the segmentation that produced the cells.

3. **Cellpose-SAM.** Planned model upgrade. It takes no diameter, which is why no diameter-derived
   filter was wired into segmentation.

4. **Explain `obs/slide`.** It appears on non-TMA runs and nothing in this pipeline writes it.
   Worth understanding before `MERGE_SPATIALDATA` starts writing its own slide identity into
   the same tables.
5. **Phase 7's remaining half: the pass-or-fail gate.** The metrics, the images and the report are
   in and published to `<outdir>/qc`; `{sample}_qc.json` is the machine-readable contract a gate
   would read. What is missing is the gate itself, and it is blocked on data rather than on code:
   every threshold worth setting needs several slides behind it, and the one slide available says
   different things than a second one might. Deliberately no thresholds and no exit code were
   written, so that a guess did not end up baked into the pipeline's verdict. Two of the four
   metrics originally listed here are still absent: Ashlar's registration residual, which exists
   only in its stderr (see Longer term), and run-level resource QC, which is structurally blocked
   (see Open).
6. **Phase 8, release.** Tag off `main`, `nf-core pipelines lint --release` first.

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

Ideas 1, 2 and 5 all want extra marker sheet columns. The sheet is already a per-sample
samplesheet column, so design that schema once rather than breaking the format three times.

## Open

Grouped by what each one asks of a reader. A finding needs no fix, a known limitation is
understood and left alone on purpose, and the last two groups are work. Nothing here now
blocks 1.0.0 on a decision.

### Findings, not bugs

- **Leiden clusters are not reproducible on the one slide we have, and that is a finding rather
  than a bug.** Across eight resolutions from 0.1 to 2.0, the best agreement between partitions from
  different random seeds was 0.596 adjusted Rand, against the 0.9 floor the QC step asks for. So no
  resolution on that slide produces a partition worth calling cell types, and the report says as
  much instead of presenting the clusters as phenotypes. Worth re-checking on a second slide before
  concluding it is a property of the data rather than of this one sample. If it holds, the honest
  move is to present clusters only as a summary of staining, or to drop them for a supervised
  gating step against known markers.

- **Every `-stub` run warns about a positional argument it was never given.** `nextflow run . -stub`
  and `-stub-run` both leave `true` in the positional args that Nextflow hands the pipeline, so the
  nf-core validator reports "the positional argument `true` has been detected" on every stub run.
  Verified on Nextflow 26.04.6 with both spellings and with `-ansi-log` absent, so it is neither the
  flag's value nor this pipeline's own strict-parameter check. Harmless, and worth knowing before
  someone chases it: stub runs are the primary feedback loop here, so this warning appears constantly.

- **Silhouette was tried and rejected for choosing a Leiden resolution; do not reach for it again.**
  It falls monotonically as resolution rises -- 0.223 at five clusters down to 0.079 at forty-three
  on the measured run -- so maximising it always returns the coarsest option on offer, and it chose
  five clusters. It is still computed and reported for reference. Selection uses seed-to-seed
  stability instead, which is not monotone and ranked resolution 0.1 _worst_, the opposite verdict.
  Both numbers are in the report's sweep table.

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

### Known limitations, accepted for now

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

- **Segmentation-time area filtering stays off, and that is now a decision rather than an
  accident.** `min_area_pixels2 = null` passes no `--min-area`, so typer supplies 0 and nothing is
  filtered. sopa's Python API would have derived `(diameter / 2)²` from the same null
  (`sopa/segmentation/methods/_cellpose.py`), but the CLI this pipeline calls declares
  `min_area: int = typer.Option(0, ...)` in `sopa/cli/segmentation.py`, so that derivation is on a
  code path this pipeline does not use. The published WSI run matches: smallest cell 4.3 px², 1%
  under 48.6 px², against the ~306 px² that `(35/2)²` implies. Wiring the derivation up explicitly
  was considered and rejected for two reasons. Cellpose-SAM takes no diameter, so a
  diameter-derived threshold is a dead end; and filtering belongs after aggregation, where it is
  reversible and visible in the QC report, rather than inside the segmentation call where it
  silently changes what was segmented. See Next items 2 and 3. Note for whoever revisits this:
  `sopa/cli/resolve.py` takes `min_area` in **microns²** while the segmentation CLI takes pixels².
  This pipeline only routes to the latter, so there is no unit mismatch today, but there would be
  if the parameter were ever wired to resolve.

- **Resource profiles are estimates** apart from `size_tiny`. Rewrite from `peak_rss` and
  `realtime` in the trace once a genuinely large slide has run.

- **H&E support** is planned; only `ome_tif` mIF input works today.

### Gaps in the tests

- **The marker sheet now says which channel is a nuclear stain, but the QC scripts do not read it
  yet.** `channel_role` is a required column and `dna` is one of its values, validated to appear in
  every cycle. The cross-cycle photobleaching check and the cluster snapshots still find the
  nuclear channel by matching the marker name against `--nuclear-pattern`, defaulting to `DAPI`,
  which works on every dataset seen so far and goes quiet on a Hoechst-stained one. Replacing the
  pattern with the column is the next branch, and touches `bin/qc_metrics.py`, `bin/qc_images.py`
  and their tests. One wrinkle to handle there: backsub drops rows whose `remove` column is set, so
  a sheet marking a `dna` channel for removal validates on the way in and has no `dna` channel left
  in the `markerout` the QC step reads.

- **`bin/set_channel_names.py` `main()` has no test for element selection.**
  `tests/unit/test_set_channel_names.py` covers marker sheet parsing and `channel_labels()`, but not
  the explicit `--element` path, the single-element fallback, or the "more than one image element"
  error. The pipeline now depends on that fallback, so the least-tested part of the script is the
  part it relies on. Needs a real spatialdata store rather than the JSON fixture `make_store`
  builds, so it is slower than the tests beside it.

- **Two inherited nf-test files** still snapshot nf-core/sopa's outputs. Rewrite as property
  assertions rather than regenerating.

- **No real-data test** for the TMA path, background subtraction, or `use_preprocessing = false`.

### Findings in the tooling

- **`ASHLAR` records a blank version on every stub run, and nothing complains.**
  `modules/nf-core/ashlar/main.nf` captures its version with
  `eval("ashlar --version | sed 's/^.*ashlar //'")`. The pipe is what saves it: `ashlar` is absent
  under `-stub`, but the exit status is `sed`'s, so the task succeeds and
  `histo_software_versions.yml` gets `ashlar:` with nothing after it. `BACKSUB` had the same
  construction without a pipe and failed loudly instead, which is how this was found. The same
  `workflow.stubRun` patch applied to BACKSUB would make it record `stub`, honestly, rather than
  a blank that reads like a captured value. Not yet done, because it is a second divergence from
  upstream.

- **nf-metro 1.1.0 cannot render the WSI line's auxiliary edge.** Adding
  `ASHLAR -->|backsub| QC_METRICS` to `docs/pipeline_paths.mmd`, which is the pre-subtraction
  image reaching QC, aborts the renderer with `CurveInvariantError: a route hanging in open
space`. Every other edge in that map renders. The edge is documented in prose in
  `docs/pipeline-paths.md` instead. Worth reporting upstream.

### Resource and configuration loose ends

- **`FLUO_ANNOTATION` is missing from the three larger size tiers**, so it inherits
  `process_medium`. The cost of that gap was measured on `REPORT`, which shared it: a one-minute
  task asked for 36 GB. `REPORT` has since been removed.

- **`PATCH_SEGMENTATION_CELLPOSE` is `process_single` but used 133% CPU.** Belongs in
  `base.config`, since its cost follows `patch_width_pixel` rather than image size.

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
