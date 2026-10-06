# Roadmap

The tracker for this project; GitHub Issues is not used. Reasoning is in
[docs/decisions.md](docs/decisions.md), larger ideas in [docs/future-ideas.md](docs/future-ideas.md).

Priorities, in order: transparency, robustness, troubleshootability.

## Status

| Phase                  | State                                                        |
| ---------------------- | ------------------------------------------------------------ |
| 0. Freeze and diagnose | Done                                                         |
| 1. Scaffold            | Done: from nf-core/sopa, rebranded, out-of-scope parts cut   |
| 2. Preprocessing       | Done: BaSiCPy, Ashlar, backsub, Coreograph                   |
| 3. TMA path            | Done: per-core processing, per-slide merge and QC page       |
| 4. Resource profiles   | Done: `size_tiny`/`small`/`medium`/`huge`, `slurm`           |
| 5. Containers          | Done: 7 images, manifest, pre-staging documented             |
| 6. Testing             | Done: unit, validation, stub (CI), exemplars (cluster)       |
| 7. QC report           | Metrics, images and reports in; thresholds need more slides  |
| 8. Release 1.0.0       | `nf-core pipelines lint --release` clean; merge and tag left |

## Verified on real data

- mIF, 3 cycles, 12 channels: 9,855 cells.
- TMA, 2 cycles: 4 cores, processed independently, merged to 29,574 cells.
- 10-cycle TMA, with and without backsub.
- Tiling: 9,855 cells as one patch versus 9,896 across six (0.4%).
- WSI, 3 cycles, 15 channels (5 background), 21,798 x 11,295 px, backsub: 142,493 cells in 72
  patches. All Phase 7 metrics and thresholds are calibrated on this one run.

Memory: 8.7 GB peak RSS in `BASICPY` on the WSI run; 1.7 GB peak across 49 tasks on the
smaller runs. `TO_SPATIALDATA` reported exactly 8.00 GiB, likely a ceiling, so treat it as
unmeasured.

## Next

1. **Aggregation beyond the mean.** Quantiles, SD, morphology. Needs a patched sopa module or
   our own step. Blocks items 2 and 3.
2. **Post-aggregation cell filtering.** Reversible and visible in QC, unlike filtering at
   segmentation.
3. **Cellpose-SAM.** Takes no diameter, so no diameter-derived filter was wired in.
4. **Explain `obs/slide`.** Appears on non-TMA runs; nothing here writes it. Understand it
   before `MERGE_SPATIALDATA` writes its own slide identity.
5. **QC pass/fail gate.** `{sample}_qc.json` is the contract it would read. Blocked on data:
   thresholds need several slides. Still missing: Ashlar registration residual (Longer term 4)
   and run-level resource QC (Open).
6. **Release.** Run the checks below, merge to `main`, tag.

## Before every release

Two runs on the cluster, by hand. Images are 8.8 GB (mIF) to 14.7 GB (with Coreograph),
too large for GitHub runners.

```bash
export HISTO_EXEMPLARS=/fast/AG_Coscia/$USER/HISTO/exemplars
bash tools/fetch_exemplars.sh          # 1.1 GB, public mcmicro S3, no credentials

export TMPDIR=/fast/AG_Coscia/$USER/tmp && mkdir -p "$TMPDIR"
export NXF_TEMP="$TMPDIR" NXF_OPTS="-Djava.io.tmpdir=$TMPDIR" NXF_OFFLINE=true

nf-test test tests/exemplar001.nf.test --profile test_exemplar001,singularity,size_small,slurm
nf-test test tests/exemplar002.nf.test --profile test_exemplar002,singularity,size_small,slurm

uvx --from nf-core nf-core pipelines lint --release
```

What each covers is in [tests/README.md](tests/README.md). Cell-count baselines are not
recorded: the ±2% assertions are commented out until the first green run sets them. Nothing
checks `use_preprocessing = false` on real data (stub only) or StarDist.

## Longer term

Costs and risks in [docs/future-ideas.md](docs/future-ideas.md).

1. **Read `.czi` metadata** for backsub exposure and channel names.
2. **Dearray across every nuclear channel** to detect cores lost between cycles.
3. **Imaging QC**: autofluorescence, artefacts, focus.
4. **Ashlar registration QC.** The residual is only in Ashlar's stderr; needs a module change.
5. **Dearray first, process each core in parallel.** Largest change; needs cores located on a
   stage-position mosaic before stitching.

Ideas 1, 2 and 5 all need extra marker sheet columns. Design that schema once.

## Open

### Findings

- **Leiden clusters are not reproducible on our one slide.** Best seed-to-seed ARI across
  resolutions 0.1 to 2.0 was 0.596, against a 0.9 floor; the report says so. Recheck on a
  second slide. If it holds, show clusters as a staining summary or switch to gating.
- **Silhouette does not work for choosing Leiden resolution.** It falls monotonically with
  resolution, so it always picks the coarsest. Still reported; selection uses seed stability.
- **Every `-stub` run warns about a positional argument `true`.** Nextflow 26.04.6 leaves it in
  the args for both `-stub` and `-stub-run`. Harmless.
- **backsub's `_backsub` suffix does not reach core IDs or any downstream name.** Only backsub's
  own outputs and the image element name inside the Zarr carry it; `SET_CHANNEL_NAMES` handles
  the latter. An earlier entry claiming otherwise was wrong.

### Known limitations

- **Booleans cannot be set false on the command line.** `--use_qc=false` is a truthy string;
  `--use_qc false` becomes `true`. Both are rejected at startup. Coercion is impossible:
  `params` ignores writes to set keys (Nextflow 26.04.6). Use a params file.
- **No run-level resource QC.** The execution trace is only final after the run, so no process
  can read it. Needs an `onComplete` hook or post-run step, once the gate exists. Trace columns:
  `status`, `attempt`, `peak_rss` (`5.1 GB`, or `-` without a container engine).
- **Segmentation-time area filtering is off by decision.** `min_area_pixels2 = null` means
  sopa's CLI uses 0. Filtering belongs after aggregation (Next 2). Note: `sopa/cli/resolve.py`
  takes `min_area` in µm², the segmentation CLI in px².
- **A marker sheet can mark its only `dna` channel for removal.** It then fails in `QC_IMAGES`,
  after the expensive steps. Fix: reject `channel_role = dna` with `remove` in
  `validateMarkerSheet`.
- **Resource profiles are estimates** apart from `size_tiny`. Rewrite from a large-slide trace.
- **H&E is not supported**; only `ome_tif` mIF input.

### Test gaps

- **`bin/set_channel_names.py` element selection is untested**: `--element`, the
  single-element fallback the pipeline relies on, and the multi-element error. Needs a real
  store.
- **The exemplar checks have not gone green yet.** Until one does, the TMA path, backsub and
  real pixels are asserted by nothing.
- **`MERGE_REPORT` guards are only hand-tested** (runs on TMA with QC, not otherwise). Needs a
  generated samplesheet with absolute paths.

### Tooling

- **nf-metro 1.1.0 cannot render `ASHLAR -->|backsub| QC_METRICS`**
  (`CurveInvariantError`). Documented in prose in `docs/pipeline-paths.md`. Report upstream.

### Resources and configuration

- **`ashlar` and `backsub` carry local patches** making `eval` version capture stub-aware.
  Drop them if fixed upstream.
- **`FLUO_ANNOTATION` is missing from the larger size tiers**, so it gets `process_medium`.
- **`PATCH_SEGMENTATION_CELLPOSE` is `process_single` but used 133% CPU.** Set it in
  `base.config`; its cost follows `patch_width_pixel`.
- **Singularity bind mounts** in `conf/slurm.config` are a commented TODO.

## Deferred deliberately

- **Channel names in the OME-TIFF header.** Would mean copying the whole image, since a task
  must not mutate its input. Names go in the Zarr instead.
- **Pixel size in the Zarr.** Would silently reinterpret `patch_width_pixel` as microns.
- **A cropped TMA fixture.** Coreograph may miss cores on a crop, giving a misleading red test.
- **`groupKey` for the cycle regroup**, and the 4.0.3 → 4.1.0 template bump.
