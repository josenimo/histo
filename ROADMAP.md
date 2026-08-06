# imaging_pipeline roadmap

Written 05.08.2026, revision 3. Supersedes the sequencing assumed in `AGENT_CONTEXT.md` §3, which
expected a fork-and-diff archaeology step. That step does not apply: see "Why the plan changed".

Priorities remain, in order: transparency, robustness, troubleshootability.

## Status of this document

**GitHub issues are the tracker. This document is the frozen reasoning behind them.**

The phases and steps below were published as 10 milestones and 57 issues on 2026-08-05 via
`create_issues.sh`. Progress lives there, not here. Do not update this document to reflect what is
done; check the issues instead.

What this document is for: the _why_. The findings from the review of the prior tree, the decisions
that were considered and rejected, the constraints that shaped the plan. An issue says "patch
coreograph to 2.4.6"; this says why the nf-core module is a downgrade, why that matters, and what was
verified. That reasoning does not go stale the way a checklist does.

Revise this document when a **decision** changes, not when a task completes. If a phase gets
resequenced or a decision in §1 is overturned, update it here and bump the revision number, then
reconcile the affected issues.

There is one scheduled exception: **at the end of each phase, add a summary to §12**. Once per phase,
not per task. That is the cadence that keeps the record useful without turning this into a changelog.

**Run `nf-core pipelines lint` at the end of every phase**, before writing the §12 entry, and record
the pass/fail/warning counts in it. The agent cannot run it: the sandbox has no network for PyPI and
no Nextflow. Write the report to a file instead and the agent will read it directly:

```
nf-core pipelines lint --markdown histo_lint_results.md 2>&1 | tee histo_lint_results.txt
```

Both patterns are gitignored. Do not fix lint findings mid-phase if the phase will delete the files
they concern; exemptions written against files that are about to disappear are wasted work.

---

## 1. Decisions settled

| Question                                     | Decision                                                                                                                                                                                                                                                                                                                                                                                           |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Starting point                               | Clone `nf-core/sopa:dev` at `c2b4e5f` as a scaffold with fresh git history. No sopa remote, no inherited TEMPLATE. Rebrand once, record source SHA in the initial commit.                                                                                                                                                                                                                          |
| Module sourcing                              | Vendor sopa's `modules/local/*` verbatim, preserving licence header, `meta.yml`, `environment.yml`, `.conda-lock/`, and a source-commit comment.                                                                                                                                                                                                                                                   |
| Tool arguments                               | Keep sopa's `argsCLI()` verbatim in `modules/local/utils.nf`.                                                                                                                                                                                                                                                                                                                                      |
| SpatialData conversion                       | Use upstream `sopa convert` with `technology = 'ome_tif'`. Delete `bin/convert_to_spatialdata.py`.                                                                                                                                                                                                                                                                                                 |
| TMA dearray                                  | Install `nf-core/modules` `coreograph`, then `nf-core modules patch` to bump the container. Delete `bin/run_coreograph.py`.                                                                                                                                                                                                                                                                        |
| **Post-module Python fixes**                 | **Undesired, but permitted as a pragmatic escape hatch.** Default to fixing at the producing step. Where going through the full module route is disproportionate, a post-hoc script is acceptable provided it is a named module with a stub, a version capture and a comment stating why the producer was not fixed. `bin/fix_core_ome_tiff.py` still goes, because a better tool exists (see §6). |
| Containers                                   | Restore upstream registry URIs. Pre-stage SIFs into the shared `NXF_SINGULARITY_CACHEDIR`. No launch-time pulls.                                                                                                                                                                                                                                                                                   |
| Params interface                             | `-params-file params.yml` is the primary interface, validated by `nextflow_schema.json`.                                                                                                                                                                                                                                                                                                           |
| Segmentation                                 | Cellpose is the primary backend for 1.0.0. StarDist retained alongside it.                                                                                                                                                                                                                                                                                                                         |
| Scope in                                     | `TISSUE_SEGMENTATION`, `CELLPOSE`, `STARDIST`, `FLUO_ANNOTATION`, `conf/predefined` mIF presets (phenocycler, macsima, hyperion).                                                                                                                                                                                                                                                                  |
| Scope out                                    | `SCANPY_PREPROCESS`, `EXPLORER_RAW`, `BAYSOR`, `COMSEG`, `PROSEG`, `SPACERANGER`, the Visium HD path, all transcript-patch paths.                                                                                                                                                                                                                                                                  |
| Reader                                       | `ome_tif` only, plus `toy_dataset` until the test fixtures are replaced in Phase 6. H&E support to be added deliberately later, not inherited.                                                                                                                                                                                                                                                     |
| Ashlar fork                                  | Deferred to nice-to-haves. Keep `josenimo/jose_ashlar:1.21.0` as-is for now.                                                                                                                                                                                                                                                                                                                       |
| `min_intensity_ratio`, `expand_radius_ratio` | Deferred until the baseline runs. 1.0.0 quantification is therefore nuclear-only.                                                                                                                                                                                                                                                                                                                  |
| Channel names and physical pixel size        | Bookmarked. Route identified via mcmicro's bftools metadata stack, see §6. Not scheduled yet.                                                                                                                                                                                                                                                                                                      |
| QC report                                    | Deferred. Scaffold the hook, build later.                                                                                                                                                                                                                                                                                                                                                          |

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

| Requirement                      | Met by `sopa convert --technology ome_tif`?                                                                                                                                                                           |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Lazy loading to Zarr             | Yes. Uses `dask_image.imread`, then `rechunk`. Never materialises the array.                                                                                                                                          |
| Pyramid                          | Yes. `_default_image_kwargs()` supplies `scale_factors` to `Image2DModel.parse`.                                                                                                                                      |
| Channel names from `markers.csv` | **No.** Read from OME-XML only, via `_ome_channels_names(path)`. There is no parameter for a channel list, and `sopa convert` passes only `technology` and `kwargs`, which `ome_tif()` does not accept names through. |
| Physical pixel size in the Zarr  | **No.** Sets `transformations={"pixels": Identity()}`. `PhysicalSizeX` is never read.                                                                                                                                 |

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
2. Rebrand: rename the pipeline to `histo` (lowercase, no separators, since Nextflow uses the repo
   name), strip `NFCORE_SOPA`, the logos, `CODE_OF_CONDUCT.md`, `ro-crate-metadata.json`, nf-core org
   CI in `.github/`, and branding in `README.md` and `utils_nfcore_sopa_pipeline`. Done across eight
   commits rather than one, since it touched roughly 40 files across config, code, CI and docs.
3. Delete out-of-scope features, grouped by reason for removal so each commit is one documented
   decision: transcript-based segmentation (`baysor`, `comseg`, `proseg`, `make_transcript_patches`);
   `explorer_raw` and `scanpy_preprocess`; the Visium HD path (`spaceranger`, `input_check`, `untar`).
   Then restrict the technology enum to `ome_tif`.

   **Ordering note:** feature removal should come _before_ rebranding, not after. Roughly a quarter
   of the branded files were deleted anyway, and lint exemptions written against files that are about
   to disappear are wasted work. This was done in the wrong order.

   **Scope changed mid-phase:** `stardist` and `fluo_annotation` were originally listed for removal
   and are now retained, StarDist as a second segmentation backend better suited to H&E nuclei, and
   fluorescence annotation for marker-based cell typing. Both must appear in at least one `-stub`
   profile, since a feature kept but never exercised rots silently.

4. Housekeeping: MIT `LICENSE` with attribution to sopa and mcmicro; `CITATIONS.md` crediting sopa,
   mcmicro and every underlying tool; `CHANGELOG.md`.
5. Vendor the nf-core community `AGENTS.md` verbatim with source URL, SHA and retrieval date, plus
   `AGENT_CONTEXT.md` layered on top.
6. Create the `TEMPLATE` orphan branch from `nf-core pipelines create` output answering "no" to the
   nf-core question, so `nf-core pipelines sync` works going forward. Note the template gap: sopa:dev
   is on tools 4.0.3, current is 4.1.0.
7. Set a real `min_area_pixels2` default in the schema rather than 0.
8. `nf-core pipelines lint` and `prek` must pass before the PR.

**Deferred out of Phase 1 to Phase 2:** none of the eleven vendored `modules/local` have a `stub:`
block, so a `-stub` run is impossible. nf-core/sopa does not support stub runs either; its
`download_pipeline.yml` has an explicit "stub run not supported" fallback. Writing eleven stubs plus
version capture for the seven modules missing it is real work, and Phase 1 was already fourteen
commits. Consequently the pre-commit config in `planning/` is **not** activated in Phase 1 either:
its `module-has-stub` hook would fail on all eleven modules and block every commit.

Exit criterion: `nf-core pipelines lint` reports no failures, and `nextflow run . --help` resolves the
whole DAG. The original criterion was a completed `-stub` run; see the deferral above.

### Phase 2. Preprocessing half

Branch: `feat/preprocess-images`.

1. `nf-core modules install basicpy backsub ashlar coreograph`. One commit each, titled
   `Install nf-core module {name}`.
2. `nf-core modules patch backsub` to v0.5.1 and `nf-core modules patch coreograph` to 2.4.6, one
   commit each. Update the `versions.yml` capture block in the same commit as each patch.
3. Build `subworkflows/local/preprocess_images`: illumination correction, then stitching and
   registration, then optional background subtraction, then optional TMA dearray.
4. Fan `BASICPY` out per cycle rather than looping inside one task.
5. Fix dfp/ffp ordering. Largely inherited: the cycle samplesheet carries an explicit
   `cycle_number`, and mcmicro's grouping sorts on it
   (`groupTuple(sort: { a, b -> a[0] <=> b[0] })`), which is the fix for P0-5. Still to add:
   - **`dfp` and `ffp` are all or nothing per sample.** JSON Schema cannot express "if present for one
     cycle, required for all", so this needs a runtime check in `validateParams`. A half-populated
     column would silently misalign illumination profiles against cycles, which is the same class of
     bug as P0-5 and just as invisible.
   - An assertion that the number of profiles matches the number of cycles before Ashlar is called.
   - Optional improvement, not required: mcmicro's `groupTuple` has no `size`, so it blocks until the
     channel completes. The samplesheet knows the cycle count per sample, so `groupKey` would release
     each sample as soon as its cycles arrive. Their own code carries a `FIXME` about this.

6. **Assert channel names survived conversion.** After `TO_SPATIALDATA`, fail the run if channel names
   are the integer fallback. sopa only logs a warning, which is not acceptable for unattended runs on
   colleagues' data. This is the cheap guard; actually fixing the names is bookmarked in §6.
7. `nf-core pipelines schema build`. Never hand-edit `nextflow_schema.json`.
8. **Add version capture to the six modules lacking it**: `aggregate`,
   `make_image_patches`, `patch_segmentation_cellpose`, `patch_segmentation_stardist`, `report`,
   `tissue_segmentation`. Provenance is priority one and the pipeline currently records almost none.
   (`explorer` was on this list; it has since been removed from the pipeline entirely. `report` also
   emitted a `versions.yml` that nothing collected, fixed when its outputs were given `emit:` names.)
9. **Stub blocks where a module creates a file.** Revised 2026-08-06; see `AGENT_CONTEXT.md` §7.

   The reasoning changed even though the outcome barely did, and the reasoning is the point. The
   original rule was "every local module needs a stub", which assumed every module produces output
   files. Five of sopa's eleven mutate the zarr in place and produce nothing new, so that rule was
   wrong. But `versions.yml` counts as a created file, and item 8 gives all eleven one, so all eleven
   end up needing a stub after all. For the pass-through modules it is three lines.

   Each stub must create exactly what the `output:` block declares. A stale stub that passes while the
   real run fails is worse than no stub.

10. **The `module-has-stub` pre-commit hook has been corrected** to key on "declares a created file"
    rather than "is a module". Verified against all eleven: it exempts only `aggregate` and
    `tissue_segmentation`, and will stop exempting them once item 8 adds their versions block, which
    is the behaviour we want.
11. **Activate the pre-commit config from `planning/`** once items 8 and 9 are done.

Exit criterion: `-stub` passes with `use_backsub = false`, `use_tma_dearray = false`. Handoff boundary
is a single stitched OME-TIFF. Note that until the §6 bookmark is picked up, channel names will be
integers and the Phase 2 item 6 assertion will fail on real data, so that assertion should be a
warning-with-exit-code decision you make consciously rather than a hard error that blocks Phase 3.

### Phase 3. TMA path

Branch: `feat/tma-dearray`. Design follows from the Phase 0 diagnosis.

**DIAGNOSIS DONE 2026-08-06, and it resolved items 1 and 5 with no code.**

UNetCoreograph 2.4.6 was run on exemplar-002 and its output inspected in QuPath and through
`sopa convert`:

- Pixel size metadata **preserved**.
- Pyramid levels **preserved**.
- `sopa convert` **succeeds**, producing a `DataTree[cyx]` with five scales.
- Cores are written as `1.ome.tif`, not `1.tif` as in 2.2.9. An extra `Coremask.tif` appears. Masks
  remain plain `.tif`, so the two output families disagree on extension.

So the original failure was a **2.2.9 problem, and the container bump alone is the fix**. No OME
repair step is needed and the `bin/fix_core_ome_tiff.py` line of work is dead. This is why the
diagnosis had to precede the patch: bumping first would have hidden which change mattered.

Channel names could not be assessed, because the input image itself carries default names. That
question is now purely about **Ashlar's output**: if Ashlar writes marker names into its OME-XML,
everything downstream inherits them. Run `histo-inspect-ome.py` on an Ashlar output to settle it.

1. ~~Fix Coreograph's output at the producing step~~ **Done: container bumped to 2.4.6.**
2. ~~Rename cores to carry unambiguous IDs~~ **Done in Phase 2.** The patched module writes
   `{slide}_core001`, zero-padded, preserving the tool's original numbering so the mapping to
   `centroidsY-X.txt` survives. Renaming is extension-agnostic, since 2.2.9 and 2.4.6 disagree.
   `tma_map`, `coremask` and `centroids` are emitted and published rather than discarded.
3. **Done.** `MERGE_SPATIALDATA` is gated on `params.use_tma_dearray`, and `validateParams` now
   rejects `use_tma_dearray` without `use_preprocessing`: dearraying is what stamps `meta.slide`,
   and without it every core would group under a null key and silently merge unrelated slides.

   It chains off `REPORT` rather than off the same upstream channel. Both give the same cores, but
   the sopa modules mutate the zarr in place and `REPORT` deletes `.sopa_cache` from it, so a
   concurrent reader would be racing a writer.

   Merge happens at the very end, after every core has been through every step independently. Chosen
   over merging before segmentation because segmenting many small dense objects scales better than
   one large sparse one, and it keeps a per-core QC report.

4. **Done.** `bin/merge_spatialdata.py` writes one element at a time with
   `SpatialData.write_element()` (verified present in the 0.8.0 API, signature
   `write_element(element_name, overwrite=False, ...)`). Two behaviours differ deliberately from the
   `legacy` script:
   - A core that cannot be read is a **hard failure**. The old script caught every exception, printed
     a warning and continued, so a slide could merge 78 of 80 cores and still exit 0.
   - It **refuses to overwrite** an existing output rather than `shutil.rmtree`-ing it.

   Merged object contains everything, images included, so a slide opens as one self-contained object.
   Tables stay one per core rather than concatenated. Elements are named `{core_id}__{original}`; the
   separator is doubled because core IDs contain single underscores.

   Peak RSS still needs measuring with `/usr/bin/time -v` on the real TMA, per §5.

5. **Bug found while wiring this, unrelated to the merge itself.** The core ID was derived with
   `replaceFirst(/\.tif$/, '')`, which leaves a trailing `.ome` on Coreograph 2.4.6 output
   (`{slide}_core001.ome.tif`). That ID becomes the sdata directory name and the prefix of every
   merged element, so cores would have been named `..._core001.ome__image`. Now extension-agnostic
   across 2.2.9 and 2.4.6, with a shape check on the result. Same class as the earlier patch bug:
   the rename was made version-proof, the thing parsing the rename was not.
6. ~~If pixel size is lost by Coreograph, fix it at the producer~~ **Not needed. 2.4.6 preserves
   pixel size**, confirmed in QuPath. The sentinel-default discussion is moot.

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
6. **Regenerate the inherited nf-test snapshots.** `tests/*.nf.test.snap` still record
   `"nf-core/sopa": "v1.0.1"` from the import. They must not be hand-edited; regenerate with
   `nf-test test --update-snapshot`, on the same CPU architecture as CI. This needs real containers,
   so it is cluster work and it blocks the Phase 1 exit criterion until done.

**Keep `.github/workflows/download_pipeline.yml`.** It counts container images before and after a
stub run and fails if the count changed, which is a machine-check of the §6 rule that nothing may be
pulled at launch time. It is the only automated guard on offline reproducibility in the repository, and
it is easy to mistake for nf-core boilerplate and delete.

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
| ---- | -------------- | ------------ | ------ |

**Corrected 2026-08-06 after installing.** The original table was built from the SHAs _mcmicro_ pins,
not from current `nf-core/modules` master, and two of the four had moved.

| Tool         | nf-core module, as installed                                | Your version                             | Action                                                                                                     |
| ------------ | ----------------------------------------------------------- | ---------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `basicpy`    | `docker.io/labsyspharm/basicpy-docker-mcmicro:1.2.0-patch5` | identical                                | None.                                                                                                      |
| `ashlar`     | `quay.io/biocontainers/ashlar:1.19.0--pyhdfd78af_0`         | `josenimo/jose_ashlar:1.21.0`, code fork | Deferred. Baseline moved from 1.18.0 to 1.19.0; the rotation-correction fork is still a separate question. |
| `backsub`    | `ghcr.io/schapirolabor/background_subtraction:v0.5.1`       | `v0.5.1`                                 | **None. Already current; the planned patch is unnecessary.**                                               |
| `coreograph` | `docker.io/labsyspharm/unetcoreograph:2.2.9`                | `2.4.6`                                  | Install, then `nf-core modules patch coreograph`. Still the only patch needed.                             |

All four emit versions through **topic channels** rather than `versions.yml`, and name their outputs
with `emit:`. Callers therefore use `MODULE.out.<name>` and cannot hit the output-arity trap that
adding `versions.yml` to the sopa modules caused. `workflows/histo.nf` already collects
`channel.topic("versions")`, so this needs no extra wiring.

`ashlar` stages its inputs as `image*/*`, `dfp*/*` and `ffp*/*`, one numbered directory each. That is
the mechanism preserving positional correspondence between cycles and illumination profiles.

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

## 6. BOOKMARK: channel names (pixel size resolved)

> **Updated 2026-08-06.** Half of this bookmark is closed. The Coreograph diagnosis showed that
> **pixel size survives** the preprocessing half, so no injection step is needed for it. What remains
> is channel names, and the question narrowed: it is now entirely about whether **Ashlar** writes
> marker names into the OME-XML of the image it hands over. `TO_SPATIALDATA` now warns loudly when
> sopa falls back to integer names, and `require_channel_names` escalates that to a hard failure once
> the preprocessing half guarantees them.

Not scheduled. Recording the route so it is not rediscovered later.

Your recollection about bftools is correct, and mcmicro has a more complete metadata stack than just
the extractor. Four pieces already exist and fit together:

| Piece             | Location                                  | What it does                                                                                                                                                                                                     |
| ----------------- | ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `BFTOOLS_SHOWINF` | `nf-core/modules`, installable            | `showinf -nopix -no-upgrade -omexml-only` per cycle, emits `*.xml`. Has `environment.yml` (`bioconda::bftools=8.0.0`) and a biocontainer.                                                                        |
| `OMEVALIDATION`   | mcmicro `modules/local`, must be vendored | Groovy `exec:` block. Parses the XML with `XmlSlurper`, extracts tile count, tile size, `PhysicalSizeX/Y` and their units, and validates they are present and consistent.                                        |
| `UPDATE_FROM_OME` | mcmicro `subworkflows/local`              | Joins the markersheet against the OME-XML, computes cumulative `channel_number` offsets across cycles, checks marker count against channel count, and errors if `exposure_time` is null when backsub is enabled. |
| `PRELUDE`         | mcmicro `subworkflows/local`              | MultiQC-ready summaries of XML, markersheet and samplesheet, with error reporting.                                                                                                                               |

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

## 7b. Deferred design improvements

Raised during Phase 2, sound, not urgent.

**Marker sheet as a samplesheet column.** Currently `--marker_sheet` is a single global file
broadcast to every sample with `combine()`, which is correct for one acquisition protocol and wrong
the moment two samples have different channel layouts. Making it a column of the cycle samplesheet
would fix that and simultaneously reduce the pipeline from two input files to one. Do this before the
first genuinely multi-sample run, not after.

**Coreograph core naming.** `coreograph` emits cores matching `*[0-9]*.tif`, a bare numeric glob with
two problems: it would match any input filename containing a digit, which all of ours do, and the
resulting core identity is a bare number with no link to its slide. Target naming is
`{sample}_core001`, zero-padded to three digits, which is ample for a slide. This is Phase 3 work and
it is the same requirement as the unambiguous core IDs already recorded there.

**The backsub-applied marker sheet is the one to use for channel names.** `BACKSUB` emits
`markerout`, a rewritten marker sheet reflecting what it actually applied, and it is already
published to `preprocessing/background_subtraction/`. No wiring was added, because nothing consumes
it yet and an emit with no consumer is a placeholder. It matters later: when channel names are
written into the OME-XML, the source must be this sheet rather than the input one, since backsub can
drop or alter channels. Whatever does the injection should take `BACKSUB.out.markerout` when backsub
ran and the original marker sheet otherwise.

**`eval()` in version outputs breaks stub runs.** `ashlar` and `backsub` declare versions with
`eval('<tool> --version')`, which Nextflow evaluates in the task environment even under `-stub`, so
the binary must exist. Worked around with shims in `tests/stub_bin` loaded by the `laptop` profile.
Arguably a Nextflow issue: an output declaration that shells out defeats the purpose of stub mode.
Worth reporting upstream. Note `ashlar` only appeared to work because its eval pipes through `sed`,
which exits 0 and silently yields an empty version.

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

### On the cluster

Raw imaging data is read-only. Never `sbatch` or `srun`; propose commands only. Never `git push`.
Never touch the shared `NXF_SINGULARITY_CACHEDIR`. Never run cleanup against `work/` directories
outside an assigned scratch. Show resolved paths before any `rm`. Prefer fixing at the producing step
over post-module Python, but a documented post-hoc module is acceptable when the alternative is
disproportionate.

### In the local agent session

Established 05.08.2026. These are mechanical facts about the tooling, not preferences. A future
session that ignores them will waste time rediscovering them.

**The agent sandbox can write to the mounted repository but cannot delete from it.** Verified with a
canary file: `cp` succeeds, `rm` returns `Operation not permitted`. Deletion requires the user to
approve a specific path, which was declined for `.git/` and should stay declined.

**Therefore the agent must not run git write commands.** `git add` and `git commit` create
`.git/index.lock` and then fail to remove it. That stale lock blocks every subsequent git write, so
one `git add` poisons the repository until the user deletes the lock by hand. This happened twice on
05.08.2026 before the cause was understood.

Consequences, which together form the working model:

- The agent prepares files with its editing tools. **The user runs every `git add` and `git commit`.**
  The agent supplies the exact command and commit message, and shows `git diff` first.
- The agent uses `git --no-optional-locks` for **all** read operations (`status`, `diff`). Plain
  `git status` takes the index lock to refresh its stat cache and will leave one behind.
- `git log`, `git show` and `git rev-parse` do not lock and are safe as-is.
- Git writes may also leave orphaned `.git/objects/*/tmp_obj_*` blobs. Harmless, but they accumulate
  and only the user can remove them. `git fsck --connectivity-only` confirms no real damage.

**Some paths are blocked from editing entirely**, not just from deletion. Attempting to edit
`.devcontainer/setup.sh` returned `resolves to a protected location`. Dotfile directories appear to be
protected regardless of the connected folder. If an edit is refused this way, either the user makes it
or the file is removed; there is no agent-side workaround.

**Commit identity** is set repository-locally to `Jose Nimo <nimojose@gmail.com>`, which is the address
verified on GitHub. The two pre-existing commits use a hostname-derived address that GitHub cannot
attribute; that inconsistency is confined to the abandoned `legacy` branch and needs no fixing.

**Issue management.** No GitHub MCP connector exists in the registry as of 05.08.2026. The agent
generates `gh issue` commands and the user runs them, batched at phase boundaries. A fine-grained
personal access token scoped to `Issues` on this repository alone would remove the friction, and was
considered and deferred: the agent reads web content, so a token in its sandbox is a token exposed to
prompt injection. Revisit if batching becomes a real cost, not before.

---

## 12. Phase log

One entry per phase, written when the phase closes. Not per task; the issues track tasks.

The point of an entry is the gap between plan and reality. If a phase went exactly as written, the
entry is two lines. If it did not, the entry is where a future reader finds out why, without having to
reconstruct it from commit messages.

Keep it short. A long entry nobody writes is worse than a short entry that gets written.

### Template

```
### Phase N: <name>  (closed YYYY-MM-DD)

Commits: <range or PR link>

Built: one or two sentences on what now exists that did not before.

Deviated: what differed from the plan in §3, and why. "Nothing" is a valid answer.

Learned: anything that changes a later phase or overturns a decision in §1.
         If this is non-empty, the affected section and issues need reconciling.

Carried forward: what was deferred out of this phase, and to where.
```

### Entries

### Phase 3: TMA path (closed 2026-08-06)

Commits: `532955d`..`ee35514`, 7 commits, 26 files.

Built: a dearrayed slide now comes back together. Each core runs the whole downstream half on its own
and `MERGE_SPATIALDATA` combines the finished stores into one object per slide, writing element by
element so peak memory is one core rather than all of them. `EXPLORER` was also removed from the
pipeline entirely.

Lint at close: **242 passed, 33 ignored, 13 warnings, 0 failed.** Warnings rose from 4, and all of the
increase was one class: eight preprocessing parameters added in Phase 2 sat at the top level of
`nextflow_schema.json` instead of inside a group, and had no descriptions at all. Grouped and
documented at the start of Phase 5, which should leave three known warnings — the removed nf-core
README badge, the deliberate flat `modules/local/utils.nf`, and the deferred 4.0.3 → 4.1.0 template
bump.

Deviated:

- **`EXPLORER` removal was not in the Phase 3 plan.** Requested mid-phase. It was cheap, but it had a
  consequence nobody predicted: `params.pixel_size` existed only to feed the Explorer export, so
  removing it deleted the one place physical scale lived. See "Learned".
- Merge placement was decided as **after everything**, not after `AGGREGATE` as §3 left open.
  Segmenting many small dense objects scales better than one large sparse one, and per-core QC
  reports survive.
- Tables are kept **one per core** rather than concatenated, so §5's concatenation caveat is moot for
  now.
- The merge chains off `REPORT` rather than off the shared upstream channel, because `REPORT` deletes
  `.sopa_cache` from the zarr in place and a concurrent reader would race it.

Learned, each of which changes something later:

- **A stub run cannot detect an incomplete commit.** Nextflow reads the working tree; git records
  something else. Both diverged here and every run still passed. `.gitignore` contained a bare
  `local/`, which git matches at any depth, so `modules/local/` was ignored. Existing modules stayed
  tracked and nothing looked wrong until a _new_ module was added there and silently omitted from its
  own commit, leaving HEAD with an `include` pointing at nothing. Compounding it, `git add` is
  all-or-nothing: one ignored path in the argument list staged none of the others, which is how a
  second commit lost its bulk. **The end-of-phase check must include a clone**, not just a stub run:
  `git clone . /tmp/check && cd /tmp/check && nextflow run . -profile laptop,test -stub`.
- **Removing EXPLORER forced the open pixel-size decision.** Option 1 in §8, "accept sopa's model and
  let physical scale live only in the Explorer bundle", no longer exists. Scale goes into the zarr or
  nowhere. The path is now known and cheap: `sopa convert` needs no patching, because
  `SpatialData.write_transformations()` rewrites only transformation metadata on an existing store.
  The trap is that the new `Scale` must go into a **new** coordinate system; redefining `global` would
  silently reinterpret `patch_width_pixel` and `min_area_pixels2` as microns.
- **Ashlar preserves pixel size and does not invent channel names.** Confirmed on real output:
  `PhysicalSize` 0.65 µm survives, `ImageDescription` is present so `tiffcomment -set` will work, and
  the 12 `Channel` elements exist but are unnamed. So §6 is now only about adding `Name` attributes to
  elements that already exist, keyed on the marker sheet's continuous `channel_number` — which makes
  that validation rule load-bearing rather than merely tidy.
- **Coreograph's version difference bit a second time.** The core ID was derived with
  `replaceFirst(/\.tif$/, '')`, leaving a trailing `.ome` on 2.4.6's `.ome.tif` output. The module
  patch had been made extension-agnostic; the code parsing its output had not. When a rename is
  version-proofed, everything that reads the renamed thing must be too.
- **`assert` inside a channel operator closure is swallowed** — already learned once with
  `validateMarkersheet`, and nearly repeated here. `error()` is the only reliable form.

Carried forward:

- Peak RSS measurement of the merge with `/usr/bin/time -v` on the real TMA. The incremental write is
  the entire point of the script and inspection cannot confirm it works.
- Real-data confirmation that core IDs appear in merged element names, and `check_qupath_paquo.py`
  against the cores. Both need containers.
- A committed TMA test profile. Blocked on a small fixture, so it goes to Phase 6; the local
  `params-exemplar002-tma.yml` covers it meanwhile.
- Writing pixel size into the zarr: now a known method rather than an open question, but unbuilt.
- Channel-name injection before `sopa convert`, still §6.

### Phase 2: Preprocessing half (closed 2026-08-06)

Commits: `b43231a`..`6058023`, 19 commits, 60 files.

Built: the two halves now meet. A cycle samplesheet goes in; illumination correction runs per cycle,
cycles are grouped and stitched, optionally background-subtracted, optionally dearrayed into cores,
and the result enters the downstream half. Every channel connection is proven by stub runs, including
the TMA fan-out where one slide becomes N independent samples.

Lint at close: **0 failed, 4 warnings**, unchanged from Phase 1. `prek` passes on all 18 hooks.

Deviated:

- Stubs were written for all eleven inherited modules after all, but for a different reason than
  planned. See §7.
- `backsub`'s planned patch was unnecessary; the nf-core module had already moved to v0.5.1.
- Coreograph's patch grew beyond a container bump into output renaming, because core identity turned
  out to be load-bearing for sopa element names.
- The Phase 0 Coreograph diagnosis finally happened here, and resolved two Phase 3 items with a
  one-line container change.

Learned, each of which changes something later:

- **`nf-core subworkflows update` changes more than the code.** `utils_nfschema_plugin` gained an
  input, which broke the caller at compile time and was caught immediately; it also required
  nf-schema 2.7.2 while `nextflow.config` pinned 2.5.1, which was silent and made every numeric CLI
  parameter fail validation. After any update, check the component's `tests/nextflow.config` for
  declared plugin versions.
- **Validation must be synchronous.** An `assert` inside a channel operator is swallowed and the run
  dies with no message. `validateIlluminationColumns` works because it is called on a plain list;
  `validateMarkersheet` did not until it was moved out of a `.map{}`. **A validation rule is not done
  until you have watched it fail.**
- **Adding an output changes a module's arity** and silently breaks every caller that unpacks
  positionally. Adding `versions.yml` to eight modules broke the whole DAG; the stub run caught it in
  seconds and nothing else would have.
- **Stub failures can describe themselves badly.** backsub reported "missing output file" when the
  file plainly existed; the real cause was a name collision with its input. When a stub failure looks
  impossible, read what the module's real `script:` block guards against.
- **Patch against the tool, not against the stub.** The Coreograph rename was written against 2.2.9's
  stub and would have renamed nothing on 2.4.6, which changed `1.tif` to `1.ome.tif`. It is now
  extension-agnostic and verified against both.
- **`eval()` in an output declaration runs even under `-stub`**, so a stub run needs the tool on PATH.
  Worked around with shims in `tests/stub_bin`.
- **Every commit should be independently valid.** Four commits referenced `ch_markersheet` without
  emitting it, because the emit sat uncommitted on disk while `nextflow run` kept passing. Running the
  tree tests the working directory, not the history.

Carried forward:

- `MERGE_SPATIALDATA` to Phase 3, written from scratch. It exists only on `legacy` and sopa has no
  equivalent, so this is the genuinely novel piece.
- Channel names, narrowed to a single experiment: does Ashlar write marker names into its OME-XML?
  `local/inspect-ome.py` answers it.
- Marker sheet as a samplesheet column, and `groupKey` for the cycle regroup: both in §7b.
- The template bump 4.0.3 to 4.1.0, still outstanding from Phase 1.

### Phase 1: Scaffold (closed 2026-08-06)

Commits: `33e0863`..`c64f520`, plus `6506dda` on TEMPLATE and `1a9277c` on dev.

Built: `main` now holds a rebranded, de-scoped pipeline derived from nf-core/sopa. The import commit
is byte-identical to upstream (tree `ec7b5cca`) so it can be verified. Out-of-scope features are gone,
the reader is restricted to `ome_tif`, and a `TEMPLATE` branch exists with ancestry established into
`dev`.

Lint at close: **0 failed, 212 passed, 33 ignored, 4 warnings**, against 13 failed / 268 passed /
20 warnings at the start. The four remaining warnings:

| Warning                                               | Status                                                             |
| ----------------------------------------------------- | ------------------------------------------------------------------ |
| `readme`: no nf-core template version badge           | Correct. This is not an nf-core pipeline.                          |
| `local_component_structure`: `modules/local/utils.nf` | Accepted false positive; reason at the top of that file.           |
| `meta_yml_exists`: `utils_nfcore_histo_pipeline`      | Accepted false positive; the template ships that file without one. |
| `nfcore_yml`: 4.0.3 should be 4.1.0                   | Real. Unblocked now the TEMPLATE branch exists.                    |

Deviated:

- Feature removal should have preceded the rebrand, not followed it. Roughly a quarter of the branded
  files were deleted anyway, and seven lint warnings evaporated with the features they described.
  Order matters more than it looks.
- The rebrand took eight commits, not one. Phase 1 as written underestimated it.
- Phase 0's Coreograph diagnosis has not happened. It needs real TMA data and gates Phase 3.
- The QC hook scaffold was dropped rather than built. An empty module is cruft, and what QC consumes
  depends on decisions not yet made.
- Stubs and the pre-commit config are deferred to Phase 2; see the note under Phase 1.

Learned, each of which changes something later:

- **sopa does not support `-stub` runs.** None of the eleven vendored modules has a stub block. The
  whole testing strategy in `AGENT_CONTEXT.md` §7 rests on `-stub` being the primary local loop, so
  Phase 2 has to build that loop before it can be relied on.
- **`nf-core pipelines schema build` syncs parameters, not enum values or descriptions.** Three
  hand-edits to `nextflow_schema.json` were unavoidable. The "never hand-edit" rule has a real gap.
- **`argsCLI` lets a parameter exist, validate, appear in `--help`, and do nothing.** `cellprob_threshold`
  was set to -6 in four test profiles and never reached Cellpose, because `extractSubArgs` did not list
  it. No linter catches this. The check that does is comparing `nextflow.config` params against
  `args.*` reads in `utils.nf`, and it is worth re-running whenever parameters change.
- **`nf-core subworkflows update` can silently change a subworkflow's interface.** `utils_nfschema_plugin`
  gained a tenth input and broke the caller at compile time, after the update had already written the
  lockfile. Run `nextflow run . --help` after every module or subworkflow update.
- **Deleting a file can break runtime code.** Removing the logos broke the completion email, which read
  one from disk. `git grep` for dangling references after every deletion.
- Three DOIs and one licence notice needed care: sopa's Zenodo DOI was inherited by the manifest and
  README, and MIT requires retaining the upstream copyright rather than replacing it.

Carried forward:

- Stubs for eleven modules, version capture for seven, and activation of the pre-commit config, all to
  Phase 2.
- Regenerating `tests/*.nf.test.snap`, which still record `nf-core/sopa v1.0.1`, to Phase 6. Needs real
  containers, so it is cluster work. `nf-test` is red until then.
- Template bump 4.0.3 to 4.1.0, now unblocked by the TEMPLATE branch.
- Two accepted standing lint warnings, both false positives rather than defects:
  `local_component_structure` on `modules/local/utils.nf`, reason documented at the top of that file;
  and `meta_yml_exists` on `subworkflows/local/utils_nfcore_histo_pipeline`, because the nf-core
  template itself ships that file with two workflows and no `meta.yml`. Adding one produced six new
  warnings, including a `meta_name` conflict that cannot be resolved while the file defines both
  `PIPELINE_INITIALISATION` and `PIPELINE_COMPLETION`.
- `ro-crate-metadata.json` was deleted as nf-core branding, but the non-nf-core template still generates
  one, so that reasoning was probably wrong. Accept it back at the first `nf-core pipelines sync`.
