# imaging_pipeline roadmap

Written 05.08.2026, revision 3. Supersedes the sequencing assumed in `AGENT_CONTEXT.md` §3, which
expected a fork-and-diff archaeology step. That step does not apply: see "Why the plan changed".

Priorities remain, in order: transparency, robustness, troubleshootability.

## Status of this document

**GitHub issues are the tracker. This document is the frozen reasoning behind them.**

The phases and steps below were published as 10 milestones and 57 issues on 2026-08-05 via
`create_issues.sh`. Progress lives there, not here. Do not update this document to reflect what is
done; check the issues instead.

What this document is for: the *why*. The findings from the review of the prior tree, the decisions
that were considered and rejected, the constraints that shaped the plan. An issue says "patch
coreograph to 2.4.6"; this says why the nf-core module is a downgrade, why that matters, and what was
verified. That reasoning does not go stale the way a checklist does.

Revise this document when a **decision** changes, not when a task completes. If a phase gets
resequenced or a decision in §1 is overturned, update it here and bump the revision number, then
reconcile the affected issues.

---

## 1. Decisions settled

| Question | Decision |
|---|---|
| Starting point | Clone `nf-core/sopa:dev` at `c2b4e5f` as a scaffold with fresh git history. No sopa remote, no inherited TEMPLATE. Rebrand once, record source SHA in the initial commit. |
| Module sourcing | Vendor sopa's `modules/local/*` verbatim, preserving licence header, `meta.yml`, `environment.yml`, `.conda-lock/`, and a source-commit comment. |
| Tool arguments | Keep sopa's `argsCLI()` verbatim in `modules/local/utils.nf`. |
| SpatialData conversion | Use upstream `sopa convert` with `technology = 'ome_tif'`. Delete `bin/convert_to_spatialdata.py`. |
| TMA dearray | Install `nf-core/modules` `coreograph`, then `nf-core modules patch` to bump the container. Delete `bin/run_coreograph.py`. |
| **Post-module Python fixes** | **Undesired, but permitted as a pragmatic escape hatch.** Default to fixing at the producing step. Where going through the full module route is disproportionate, a post-hoc script is acceptable provided it is a named module with a stub, a version capture and a comment stating why the producer was not fixed. `bin/fix_core_ome_tiff.py` still goes, because a better tool exists (see §6). |
| Containers | Restore upstream registry URIs. Pre-stage SIFs into the shared `NXF_SINGULARITY_CACHEDIR`. No launch-time pulls. |
| Params interface | `-params-file params.yml` is the primary interface, validated by `nextflow_schema.json`. |
| Segmentation | Cellpose only for 1.0.0. |
| Scope in | `TISSUE_SEGMENTATION`, `conf/predefined` mIF presets (phenocycler, macsima, hyperion). |
| Scope out | `STARDIST`, `SCANPY_PREPROCESS`, `FLUO_ANNOTATION`, `BAYSOR`, `COMSEG`, `PROSEG`, `SPACERANGER`, all transcript-patch paths. |
| Ashlar fork | Deferred to nice-to-haves. Keep `josenimo/jose_ashlar:1.21.0` as-is for now. |
| `min_intensity_ratio`, `expand_radius_ratio` | Deferred until the baseline runs. 1.0.0 quantification is therefore nuclear-only. |
| Channel names and physical pixel size | Bookmarked. Route identified via mcmicro's bftools metadata stack, see §6. Not scheduled yet. |
| QC report | Deferred. Scaffold the hook, build later. |

### Why the plan changed

`AGENT_CONTEXT.md` §3 assumed a hand-modified copy of nf-core/sopa that could be diffed against the
release it branched from. The repository is not that. It is two commits, 34 files, `main` only, with
no nf-core scaffolding: no `nextflow_schema.json`, `modules/`, `conf/`, `modules.json`, `assets/`,
`nf-test.config`, `.nf-core.yml`, `CITATIONS.md`, `CHANGELOG.md`, `LICENSE` or `README.md`. All twelve
processes are defined inline in two subworkflow files.

There is no branch point, so there is nothing to diff. That removes the archaeology step, and also
removes the main argument against starting from sopa's tree: there is no divergent history to
preserve. `AGENT_CONTEXT.md` §2's "do NOT fork nf-core/sopa" is amended rather than overruled. The
objection was the permanent merge conflict against an actively developed repository; cloning as a
scaffold with fresh history takes sopa's machinery without that obligation, since rebranding
guarantees automated merges conflict regardless. The realistic upgrade path either way is a manual
diff against the local sopa clone at `/Users/jnimoca/Jose_BI/1_Repositories/sopa`.

---

## 2. Findings

### P0-1. The converter must go, but `sopa convert` does not meet all four requirements

`bin/convert_to_spatialdata.py` calls `tifffile.imread()` then `Image2DModel.parse()`. It does not
call `sopa convert`. It loads whole images into RAM, writes no pyramid, overwrites channel names with
`"0"`, `"1"`, `"2"`, and drops pixel size. On 5 GB to 100 GB inputs through a process configured at
8 GB, it cannot work. Agreed: it is deleted.

Reading the actual source of sopa's reader (`sopa/io/reader/`, `ome_tif()`) against your four stated
requirements gives a mixed result:

| Requirement | Met by `sopa convert --technology ome_tif`? |
|---|---|
| Lazy loading to Zarr | Yes. Uses `dask_image.imread`, then `rechunk`. Never materialises the array. |
| Pyramid | Yes. `_default_image_kwargs()` supplies `scale_factors` to `Image2DModel.parse`. |
| Channel names from `markers.csv` | **No.** Read from OME-XML only, via `_ome_channels_names(path)`. There is no parameter for a channel list, and `sopa convert` passes only `technology` and `kwargs`, which `ome_tif()` does not accept names through. |
| Physical pixel size in the Zarr | **No.** Sets `transformations={"pixels": Identity()}`. `PhysicalSizeX` is never read. |

Two consequences.

**Channel names are an mcmicro-side problem, not a sopa-side one.** The names must be correct in the
OME-XML of the stitched OME-TIFF before it crosses the handoff boundary. This actually fits your
no-post-fix constraint well: fix at the producer. But it means Ashlar's output must carry channel
names from `markers.csv`, and baseline Ashlar does not take a marker file, so this needs solving in
Phase 2 rather than assumed away.

Worse, the fallback is silent:

```python
if len(channel_names) != len(image):
    channel_names = [str(i) for i in range(len(image))]
    log.warning(f"Channel names couldn't be read. Using {channel_names} instead.")
```

A `log.warning` only. So if the OME-XML lacks channel names, sopa produces exactly the same
integer-named channels your script did, and an unattended run on a colleague's dataset loses every
marker name with no failure. This needs a hard assertion after conversion.

**Pixel size is not in sopa's data model at this step.** sopa carries physical scale as
`params.pixel_size`, consumed at the Explorer export step, not as a coordinate transformation in the
Zarr. Your requirement diverges from how sopa works. The spatialdata-native way to encode it would be
a `Scale` transformation into a microns coordinate system instead of `Identity()` into `"pixels"`.
That is a small, defensible edit to a vendored module and a good upstream contribution to sopa, but it
is a divergence and needs your decision. See §7.

### P0-2. Coreograph runs `docker run` from inside a process, and its fallback fabricates data

`bin/run_coreograph.py` shells out to `docker run --platform linux/amd64 ...
labsyspharm/unetcoreograph:2.4.6` via `subprocess.run(..., shell=True)`. There is no Docker daemon on
the SLURM cluster, so this always fails and always reaches the fallback. The fallback crops the four
corner quadrants of the image, each capped at 3200 px (`min(3200, h // 2)`), and names them `1.tif`
to `4.tif`.

So with `use_tma_dearray = true` on the cluster, the pipeline emits four corner crops labelled as
cores, silently. Given that core identity is a hard requirement, this is the most severe defect in the
repository. It is also nested containerisation: the process declares
`container 'labsyspharm/unetcoreograph:2.4.6'` and then tries to launch that same image from inside
it.

Fix: install the `nf-core/modules` `coreograph` module, which invokes `/app/UNetCoreograph.py`
directly in the declared container. No fallback of any kind. If Coreograph fails, the run fails.

### P0-3. The real Coreograph problem is unresolved and needs diagnosis before design

You recall that `technology = 'ome_tif'` worked, and that the failure was specifically Coreograph
output into `sopa convert`, caused by formatting in Coreograph's TIFFs. `bin/fix_core_ome_tiff.py`
sets `axes='CYX'`, `photometric='minisblack'`, `ome=True` and injects `Channel` names, which is strong
evidence the problem is axis interpretation and missing OME channel metadata rather than pixel data.

Two hard constraints in sopa's reader are the likely trip points:

```python
if image.ndim == 4:
    assert image.shape[0] == 1, "4D images not supported"
elif image.ndim != 3:
    raise ValueError(f"Number of dimensions not supported: {image.ndim}")
```

A single-channel core gives `ndim == 2` and raises. An ImageJ hyperstack can give `ndim == 4`.

There is also a naming problem nobody has hit yet. The reader derives the element name from the
filename: `image_name = Path(path).absolute().name.split(".")[0]`. Coreograph emits `1.tif`, `2.tif`,
so element names become `1`, `2`. Your requirement is unambiguous core IDs in element names, so cores
must be renamed to something like `{sample}_core_{n}.ome.tif` before conversion. A `mv` loop inside
the patched module is shell at the producing step, which is within your constraint.

Phase 3 therefore begins with diagnosis, not implementation. See §3.

### P0-4. No process emits `versions.yml`

Zero of twelve. No provenance record anywhere, which is a direct hit on the top priority. Vendoring
sopa's modules and installing the mcmicro modules resolves it; both carry version capture blocks.

### P0-5. ASHLAR dfp/ffp ordering is unguarded

Ashlar requires positional correspondence between input images and illumination profiles. The
`main.nf` path for pre-computed `dfp`/`ffp` builds those lists via `groupTuple()`, which gives no
ordering guarantee. Misordered profiles produce silently misregistered output rather than an error.
Fix with an explicit cycle index in the meta map, sorted, plus a length assertion.

### P0-6. `min_area` is hardcoded to 0

`--min-area 0` disables all small-object filtering, admitting debris and nuclear fragments into the
feature table. Confirmed arbitrary. Restoring `argsCLI` exposes `min_area_pixels2`; sopa's mIF presets
supply starting values (38 for phenocycler at 20X, 400 for macsima). Existing results should be
reinterpreted accordingly.

### P1 findings

- `MERGE_SPATIALDATA` is called unconditionally in `SOPA_SPATIAL`. For non-TMA input it merges a
  single sample with itself. Gate on `params.use_tma_dearray`.
- `merge_spatialdata.py` accumulates every core's images, shapes and tables in Python dicts before a
  single `.write()`. With hundreds of cores this exhausts RAM. Fix in §5.
- `params.coreograph_args` is computed into `def args` and never used. The configured
  `--channel 0 --downsampleFactor 3 --buffer 2` has no effect.
- Cellpose hardcodes `--no-gpu` while the `slurm` profile sets `containerOptions '--nv'`. The profile
  enables GPU passthrough and the command line disables GPU.
- `containerOptions '--platform linux/amd64'` on `COREOGRAPH` is a Docker flag. It fails under
  Apptainer.
- `BASICPY` loops over all cycles inside one task. No parallelism, and one bad cycle fails the slide.
- `groupKey` is dropped. Upstream uses `groupKey(meta.sdata_dir, n_patches)` so groups release once
  the expected count arrives. Plain `groupTuple(by: 0)` blocks until the channel completes, which
  serialises multi-sample runs.
- `RESOLVE_CELLPOSE` uses `cp` where upstream uses `mv`, doubling peak disk.
- `max_memory` and `max_cpus` are deprecated in favour of `resourceLimits`.
- `publishDir` is set in process bodies with `mode: 'copy'` hardcoded, rather than in
  `conf/modules.config` with `params.publish_dir_mode`, which is not defined.
- `bin/` scripts are invoked as `$projectDir/bin/script.py` rather than by name on `PATH`.
- `AGENT_CONTEXT.md` is untracked.

---

## 3. Phases

One branch per phase, PR into `dev`. Commits are single-concern.

### Phase 0. Freeze and diagnose

Branch: none, work on `legacy`.

1. Commit `AGENT_CONTEXT.md`, currently untracked. Commit this roadmap.
2. Rename `main` to `legacy` and push. Kept as a reference for what the parameters and Python glue
   did. Never merged forward.
3. **Diagnose the Coreograph output problem.** This is a read-only investigation on one real TMA, not
   a fix, and it gates the Phase 3 design. Take one Coreograph core straight out of the container with
   no post-processing and record:
   - `tifffile.TiffFile(core).series[0].axes` and `.shape`, and `len(tif.pages)`
   - whether an OME-XML block exists, and whether it contains `Channel` elements and `PhysicalSizeX`
   - `is_imagej`, `is_ome`, `photometric` on page 0
   - what `dask_image.imread.imread(core).ndim` returns, since that is what sopa branches on
   - the exact traceback from `sopa convert --technology ome_tif` on the raw core

   Do the same for the Ashlar output that fed Coreograph, so the comparison isolates what Coreograph
   changes. Record the findings in the repo. This determines whether the fix is a container bump to
   2.4.6, a patched module, or an upstream UNetCoreograph change.
4. Reuse `bin/check_qupath_paquo.py` here as a diagnostic, then move it to `tests/` as an acceptance
   check. It is a good test for "cores are ingestable by QuPath" and a bad pipeline step.

Exit criterion: a written diagnosis of what Coreograph produces and why sopa rejects it.

**Decision branch out of Phase 0.** If the diagnosis shows the Coreograph problem is metadata rather
than pixel data, which the evidence currently suggests, then the §6 metadata stack stops being a
bookmark and becomes the fix. In that case pull it forward into Phase 2 rather than deferring it:

- `BFTOOLS_SHOWINF` on the Coreograph cores tells you precisely what is missing, using the same tool
  that will later repair it.
- `OMEVALIDATION` already raises `Images are missing pixel physical size metadata`, so the loud failure
  you want for cores comes free.
- `tiffcomment -set` repairs the OME-XML at the producing step, which satisfies the no-post-hoc-Python
  preference properly rather than by exception.
- Channel names and pixel size then get solved once, for both the stitched image and the cores, instead
  of twice.

The cost of pulling it forward is that Phase 2 grows and the `-stub` gap in `UPDATE_FROM_OME` arrives
earlier. The cost of not pulling it forward, if the diagnosis points this way, is building a
throwaway Coreograph fix and then replacing it. Decide once the diagnosis is in hand, not before.

### Phase 1. Scaffold

Branch: `feat/scaffold`.

1. Copy the `nf-core/sopa:dev` tree at `c2b4e5f`. Fresh `git init`, no sopa remote. Initial commit
   records source repository, SHA and retrieval date in the message body.
2. Rebrand as one commit: rename the pipeline to `imagingpipeline` (lowercase, no separators, since
   Nextflow uses the repo name), strip `NFCORE_SOPA`, `assets/nf-core-sopa_logo_*`, `docs/images/`,
   `CODE_OF_CONDUCT.md`, `ro-crate-metadata.json`, nf-core org CI in `.github/`, and branding in
   `README.md` and `utils_nfcore_sopa_pipeline`.
3. Delete out-of-scope features, one commit per feature so each deletion is documented: `baysor`,
   `comseg`, `proseg`, `stardist`, `spaceranger`, `scanpy_preprocess`, `fluo_annotation`,
   `make_transcript_patches`, `explorer_raw`, and their `conf/predefined/*`, schema entries and
   nf-tests.
4. Housekeeping: MIT `LICENSE` with attribution to sopa and mcmicro; `CITATIONS.md` crediting sopa,
   mcmicro and every underlying tool; `CHANGELOG.md`.
5. Vendor the nf-core community `AGENTS.md` verbatim with source URL, SHA and retrieval date, plus
   `AGENT_CONTEXT.md` layered on top.
6. Create the `TEMPLATE` orphan branch from `nf-core pipelines create` output answering "no" to the
   nf-core question, so `nf-core pipelines sync` works going forward. Note the template gap: sopa:dev
   is on tools 4.0.3, current is 4.1.0.
7. Set a real `min_area_pixels2` default in the schema rather than 0.
8. `nf-core pipelines lint`, `prek`, and a `-stub` run must all pass before the PR.

Exit criterion: `-stub` run completes on the `test` profile, cellpose path only.

### Phase 2. Preprocessing half

Branch: `feat/preprocess-images`.

1. `nf-core modules install basicpy backsub ashlar coreograph`. One commit each, titled
   `Install nf-core module {name}`.
2. `nf-core modules patch backsub` to v0.5.1 and `nf-core modules patch coreograph` to 2.4.6, one
   commit each. Update the `versions.yml` capture block in the same commit as each patch.
3. Build `subworkflows/local/preprocess_images`: illumination correction, then stitching and
   registration, then optional background subtraction, then optional TMA dearray.
4. Fan `BASICPY` out per cycle rather than looping inside one task.
5. Fix dfp/ffp ordering with an explicit cycle index and a length assertion.
6. **Assert channel names survived conversion.** After `TO_SPATIALDATA`, fail the run if channel names
   are the integer fallback. sopa only logs a warning, which is not acceptable for unattended runs on
   colleagues' data. This is the cheap guard; actually fixing the names is bookmarked in §6.
7. `nf-core pipelines schema build`. Never hand-edit `nextflow_schema.json`.
8. Stub blocks for every local module, in the same commit as the module.

Exit criterion: `-stub` passes with `use_backsub = false`, `use_tma_dearray = false`. Handoff boundary
is a single stitched OME-TIFF. Note that until the §6 bookmark is picked up, channel names will be
integers and the Phase 2 item 6 assertion will fail on real data, so that assertion should be a
warning-with-exit-code decision you make consciously rather than a hard error that blocks Phase 3.

### Phase 3. TMA path

Branch: `feat/tma-dearray`. Design follows from the Phase 0 diagnosis.

1. Fix Coreograph's output at the producing step, based on the diagnosis. In preference order:
   container bump to 2.4.6 alone if that resolves it; a patched module with a corrected write step;
   an upstream UNetCoreograph fix. No `bin/fix_core_ome_tiff.py`, no post-hoc Python.
2. Rename cores to carry unambiguous IDs before conversion, since sopa derives element names from
   filenames. A `mv` loop in the patched module, using Coreograph's `centroidsY-X.txt` and
   `TMA_MAP.tif` so the core-ID-to-position mapping is recorded rather than inferred.
3. Gate `MERGE_SPATIALDATA` on `params.use_tma_dearray`.
4. Rewrite the merge incrementally, see §5.
5. If pixel size is genuinely lost by Coreograph, that is a producer-side fix too. It must fail loudly
   rather than defaulting. If a default is unavoidable, use 1.0 µm/px as an obviously-wrong sentinel,
   not 0.65, and emit a warning that reaches the report.

Exit criterion: `-stub` passes with `use_tma_dearray = true`; on real data, core IDs are visible in
element names and `check_qupath_paquo.py` passes against the cores.

### Phase 4. Resource profiles

Branch: `feat/size-profiles`.

1. `conf/size_small.config`, `conf/size_medium.config`, `conf/size_huge.config`, each with `TODO`
   markers against every `cpus`, `memory` and `time` value for you to fill from real run data.
2. Replace `max_memory` and `max_cpus` with `resourceLimits`.
3. `conf/mdc.config` institutional profile for the SLURM setup.
4. Review the `errorStrategy` retry on exit codes 137, 140, 7, 125 against nf-core `base.config`.

### Phase 5. Containers

Branch: `feat/containers`.

1. Restore upstream registry URIs in every vendored sopa module. Remove the eight hardcoded
   `/fast/AG_Coscia/software/singularity/python_sopa.sif` references from module bodies.
2. Container manifest script in version control listing every image URI, alongside `modules.json`.
3. Document the pre-staging workflow: `nf-core pipelines download` on a well-connected machine, then
   rsync into the shared cache.

### Phase 6. Testing

Branch: `feat/tests`.

1. `test` profile with a cropped two-channel tile, and a four-core TMA fixture.
2. `test_full` profile against a real dataset.
3. Test data in a small repository of your own.
4. `-stub` run in CI. `nf-test test tests/`.
5. `check_qupath_paquo.py` wired in as an acceptance check on the TMA fixture.

### Phase 7. QC report

Branch: `feat/qc-report`. Deferred. Scaffold the module and channel wiring in Phase 1 so the hook
exists.

Open design question for when this starts: unattended runs on colleagues' data need machine-readable
pass or fail signals, not only an HTML to eyeball. Candidates: cell count per core, mean and
saturated-pixel fraction per channel, Ashlar registration residual, fraction of patches with zero
cells, and whether channel names are real rather than integers. Acceptance thresholds need to come
from you.

### Phase 8. Release 1.0.0

Tag off `main` once illumination correction, stitching and registration, and segmentation run
end-to-end, even with optional steps unfinished. `nf-core pipelines lint --release` first. Note in the
release that quantification is nuclear-only, since `expand_radius_ratio` is deferred.

---

## 4. Version table

Every nf-core module ships older than what you run.

| Tool | nf-core module | Your version | Action |
|---|---|---|---|
| `basicpy` | `docker.io/labsyspharm/basicpy-docker-mcmicro:1.2.0-patch5` | identical | Install, no patch. |
| `ashlar` | `biocontainers/ashlar:1.18.0--pyhdfd78af_0` | `josenimo/jose_ashlar:1.21.0`, code fork | Deferred. Keep the fork image, vendor to `modules/local/ashlar` with provenance documented. |
| `backsub` | `ghcr.io/schapirolabor/background_subtraction:v0.4.1` | `v0.5.1` | Install, then `nf-core modules patch backsub`. |
| `coreograph` | `docker.io/labsyspharm/unetcoreograph:2.2.9` | `2.4.6` | Install, then `nf-core modules patch coreograph`. |

Module SHAs pinned in mcmicro's `modules.json`: `ashlar c7c25b63`, `backsub 41dfa3f7`,
`basicpy a46512fa`, `coreograph 41dfa3f7`.

For every patch: verify an amd64 image for that tag exists, and update the `versions.yml` capture
block in the same commit. A hardcoded version string left unbumped makes provenance silently wrong.

`coreograph`, `basicpy` and `backsub` have no `environment.yml`, so they are container-only and
amd64-only. Only `ashlar` has a conda recipe. That matters for upstreaming: the Ashlar fork has a
bioconda route, but bumping `backsub` and `coreograph` means bumping a container tag in the nf-core
module, since there is no bioconda recipe to fix.

---

## 5. Merging TMA cores without exhausting RAM

Current code builds `images_dict`, `shapes_dict` and `tables_dict` across all cores, then calls
`.write()` once. Two separate problems.

Images are already lazy. `sd.read_zarr` returns dask-backed arrays, so holding them in a dict is
cheap; the blowup happens because a single `.write()` at the end materialises everything at once.
The fix is `SpatialData.write_element()`: write an empty SpatialData to the target Zarr first, then
loop over cores and write one element at a time, letting each core's dask graph be evaluated and
released before the next. Peak memory becomes one core rather than all cores.

Tables are the exception. spatialdata does not support incremental partial changes to a table, so the
per-core AnnData objects must be concatenated in memory. This is tolerable: a table is one row per
cell with one column per channel, so hundreds of cores is tens of megabytes, not gigabytes. Keep the
tables as separate per-core elements if concatenation ever becomes a problem, which also preserves
core identity more cleanly.

Practical consequence for Phase 3: the merge module reads lazily, writes per element, and never holds
more than one core's image graph. Verify with a `/usr/bin/time -v` peak RSS measurement on the real
TMA rather than by inspection.

---

## 6. BOOKMARK: channel names and physical pixel size

Not scheduled. Recording the route so it is not rediscovered later.

Your recollection about bftools is correct, and mcmicro has a more complete metadata stack than just
the extractor. Four pieces already exist and fit together:

| Piece | Location | What it does |
|---|---|---|
| `BFTOOLS_SHOWINF` | `nf-core/modules`, installable | `showinf -nopix -no-upgrade -omexml-only` per cycle, emits `*.xml`. Has `environment.yml` (`bioconda::bftools=8.0.0`) and a biocontainer. |
| `OMEVALIDATION` | mcmicro `modules/local`, must be vendored | Groovy `exec:` block. Parses the XML with `XmlSlurper`, extracts tile count, tile size, `PhysicalSizeX/Y` and their units, and validates they are present and consistent. |
| `UPDATE_FROM_OME` | mcmicro `subworkflows/local` | Joins the markersheet against the OME-XML, computes cumulative `channel_number` offsets across cycles, checks marker count against channel count, and errors if `exposure_time` is null when backsub is enabled. |
| `PRELUDE` | mcmicro `subworkflows/local` | MultiQC-ready summaries of XML, markersheet and samplesheet, with error reporting. |

Two things this gives you beyond what you asked for.

**`OMEVALIDATION` already fails loudly on missing pixel size.** Its nf-tests assert the error string
`Images are missing pixel physical size metadata`. That is exactly the behaviour you wanted in place of
`fix_core_ome_tiff.py`'s silent 0.65 µm/px default, and it is already written and tested.

**`PRELUDE` is a pre-flight validation gate.** It checks samplesheet, markersheet and OME metadata
consistency before the expensive steps run. For unattended runs on colleagues' datasets, catching a
marker count mismatch in seconds rather than after a six-hour Ashlar job is worth more than most of the
QC report. Worth considering ahead of Phase 7.

### The writing side

Extraction is solved. Writing marker names back into the stitched OME-TIFF's OME-XML is the missing
half, and bftools covers it:

```
tiffcomment sample.ome.tif                  # extract
tiffcomment -set 'newmetadata.xml' sample.ome.tif   # inject
```

So the shape of the eventual fix is: `BFTOOLS_SHOWINF` to get the XML, `UPDATE_FROM_OME` to reconcile
it with `markers.csv`, then `tiffcomment -set` to write the corrected XML back. All at the producing
step, all tool-level, no Python. Physical pixel size rides along in the same XML, so `OMEVALIDATION`
puts it in the meta map and it can feed both `params.pixel_size` for Explorer and a `Scale`
transformation if that option is chosen.

### Caveats to check when this is picked up

- **`tiffcomment` errors if the `ImageDescription` TIFF tag is absent.** Documented limitation. Likely
  relevant to Coreograph cores, which is one more reason the Phase 0 diagnosis should record whether
  that tag exists.
- **`UPDATE_FROM_OME` contains `if (workflow.stubRun) { return }`**, so it is skipped entirely in stub
  runs. Since `-stub` is your primary feedback loop, adopting this subworkflow adds a code path that
  `-stub` does not exercise. Worth knowing before relying on it.
- `OMEVALIDATION` uses a Groovy `exec:` block, so it runs on the head node with no container and emits
  no `versions.yml`. Acceptable, but it is not a normal module and cannot be `nf-core modules install`ed.
- bftools is Java, so `bftools:8.0.0--hdfd78af_0` may well run on Apple Silicon. If so this would be a
  rare module you can actually test locally rather than only via `-stub`. Worth five minutes to check.
- mcmicro's stack assumes the multi-cycle samplesheet shape (`cycle_number`, `channel_count`). Adopting
  it constrains your input schema, which is fine for the mIF path but needs thought for the
  single-prestitched-image path.

---

## 7. Parameters unlocked by restoring `argsCLI`

Currently unreachable. `argsCLI()` is not a nested-map API; it maps flat parameters, using the names
already in your `nextflow.config`, into CLI strings, skipping nulls. `-params-file params.yml` is
unaffected either way.

Segmentation: `min_area_pixels2`, `flow_threshold`, `cellpose_model_type`, `pretrained_model`,
`cellpose_use_gpu`, `cellpose_kwargs`.

Preprocessing: `clip_limit`, `clahe_kernel_size`, `gaussian_sigma`.

Patchify: `image_scale`.

Aggregation: `expand_radius_ratio`, `min_intensity_ratio`. Both deferred by your decision, so 1.0.0
quantifies nuclear masks only with no membrane expansion.

Explorer: `pixel_size`, `ram_threshold_gb`, `lazy`.

Tissue segmentation: `level`, `mode`, `tissue_segmentation_kwargs`.

Correction to an earlier note: `cellprob_threshold` appears in sopa's `conf/predefined/*` configs but
is never read by `extractSubArgs`, so it does not reach the Cellpose CLI upstream either. If you want
it, that is an edit to the vendored `utils.nf` and a candidate upstream fix.

---

## 8. Open decisions

**Physical pixel size in the Zarr.** You want it in the image metadata. sopa does not put it there;
it carries physical scale as `params.pixel_size` consumed at Explorer export, with the image itself
on an `Identity()` transformation into a `"pixels"` coordinate system. Three options:

1. Accept sopa's model. Set `params.pixel_size`, physical scale exists only in Explorer output. No
   divergence, but the Zarr is not self-describing, and if a colleague opens it in napari the scale is
   wrong.
2. Edit the vendored `TO_SPATIALDATA` to read `PhysicalSizeX` from the OME-XML and emit a `Scale`
   transformation into a microns coordinate system. Spatialdata-native, self-describing, and a good
   upstream contribution to sopa. But it is a divergence in a vendored module, and it makes the Zarr
   differ from what stock sopa produces, which affects diffability.
3. Both: option 2 plus setting `params.pixel_size` for Explorer.

I lean to 3, with the `Scale` change offered upstream so the divergence is temporary. Needs your call,
but not until the §6 bookmark is picked up, since `OMEVALIDATION` is what would supply the value.

**Whether to adopt mcmicro's `PRELUDE` ahead of Phase 7.** It is a pre-flight validation gate that
catches samplesheet, markersheet and OME metadata inconsistencies in seconds, before Ashlar runs. For
unattended runs on colleagues' data that may be worth more than the QC report it would precede.
Adopting it means accepting mcmicro's multi-cycle samplesheet shape. See §6.

---

## 9. Nice to haves, deferred

**The Ashlar rotation-correction fork.** `josenimo/jose_ashlar:1.21.0` derives from
`jmuhlich/ashlar` branch `rotation-correction`, 27 commits ahead of `ashlar/master` and 1 behind.
Worth noting: jmuhlich is Ashlar's maintainer, so this is the maintainer's own feature branch, not a
third-party fork. That makes eventual upstreaming likely without your effort, and makes vendoring a
genuinely temporary measure rather than a permanent liability. Two things worth doing cheaply when you
have time: check whether the branch has since merged to `ashlar/master`, and put the Dockerfile for
the image in version control so the tag is reproducible.

**Upstream contribution track.** Each removes a private maintenance burden.

1. `backsub` v0.5.1 container bump to the nf-core module. A few lines.
2. `coreograph` 2.4.6 container bump to the nf-core module.
3. The `Scale` transformation for physical pixel size to sopa's `ome_tif` reader, if option 2 or 3
   above is chosen.
4. A hard failure rather than a `log.warning` when sopa's channel-name read falls back to integers.
5. TMA support to nf-core/sopa: core-aware element naming and the merge step. sopa has no equivalent,
   and it is the most novel piece of this pipeline.

---

## 10. Open items still to verify

- Whether the Coreograph 2.4.6 container alone resolves the OME formatting problem, or whether the
  module needs patching. Answered by the Phase 0 diagnosis.
- Whether Coreograph cores carry an `ImageDescription` TIFF tag, since `tiffcomment` errors without
  one. Add to the Phase 0 diagnosis checklist.
- Whether `bftools:8.0.0--hdfd78af_0` runs on Apple Silicon. If it does, it is a rare locally-testable
  module.
- Wave and Seqera Containers config keys, free-tier limits and image retention policy. Most likely of
  the `AGENT_CONTEXT.md` §10 items to have moved.
- Whether an institutional registry exists at MDC to mirror into, given the flaky cluster network.
- Whether the current Nextflow version stages containers during `-stub` runs.
- Whether `jmuhlich/ashlar` `rotation-correction` has merged upstream since.

Confirmed this session: nf-core/tools is at 4.1.0, released 29.07.2026; sopa:dev sits on template
4.0.3. sopa's `ome_tif` reader is lazy and pyramidal, reads channel names from OME-XML only with a
silent integer fallback, and does not read physical pixel size. `SpatialData.write_element()` supports
incremental writes; tables do not support incremental partial changes. `tiffcomment -set` injects
replacement OME-XML into an OME-TIFF but requires an existing `ImageDescription` tag. mcmicro ships
`BFTOOLS_SHOWINF` as an installable nf-core module with a conda recipe, plus `OMEVALIDATION`,
`UPDATE_FROM_OME` and `PRELUDE` as vendorable local pieces.

---

## 11. Agent constraints reaffirmed

Raw imaging data is read-only. Never `sbatch` or `srun`; propose commands only. Never `git push`.
Never touch the shared `NXF_SINGULARITY_CACHEDIR`. Never run cleanup against `work/` directories
outside an assigned scratch. Show resolved paths before any `rm`. Prefer fixing at the producing step
over post-module Python, but a documented post-hoc module is acceptable when the alternative is
disproportionate.
