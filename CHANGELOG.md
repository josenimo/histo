# josenimo/histo: Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## v1.1.0dev

### Added

- Marker sheet `remove` is checked at startup: with backsub, at least one `dna` channel must stay
  and segmentation channels must not be removed; without backsub, `remove` warns that it is ignored.
- A startup warning when Ashlar's alignment channel or Coreograph's dearray channel is not a
  `dna` channel in the marker sheet.

### Fixed

- `obs/slide` is the samplesheet sample, not sopa's image element name, which carried
  `_backsub` and went stale after the TMA merge. TMA cells also get `obs/core_id`.

## v1.0.0 - [2026-10-06]

First release. Both halves run end to end on real data: raw cycles through illumination
correction, stitching, optional background subtraction and TMA dearray, then segmentation,
aggregation and a QC report. Verified on mIF, TMA and WSI slides; see
[ROADMAP.md](ROADMAP.md) for what each run measured and what is deliberately absent.

### Compatibility

This release fixes the input contract. The samplesheet and marker sheet columns that exist
now will keep working:

- **Samplesheet** — `sample`, `cycle_number`, `image_tiles`, `marker_sheet`, and the optional
  `dfp` and `ffp`.
- **Marker sheet** — `channel_number`, `cycle_number`, `marker_name`, `channel_role` required;
  `channel_compartment`, `filter`, `excitation_wavelength`, `emission_wavelength`, `exposure`,
  `background`, `remove` optional.

Three planned features want more marker sheet columns: reading `.czi` metadata, dearraying
across every nuclear channel, and dearraying before stitching. Those columns will be **added
as optional**, in minor releases. A column that exists today will not change meaning or become
required without a major version. Say so here rather than in a design note, because the
previous entry said "the input format is still changing" and that is no longer a licence this
project grants itself.

Boolean parameters still cannot be set on the command line. Use a params file. The attempt is
rejected at startup rather than silently inverted; the reasoning is in ROADMAP under Known
limitations.

### Added

- The preprocessing half, from nf-core/mcmicro: BaSiCPy and ASHLAR under `use_preprocessing`,
  then optional background subtraction (`use_backsub`) and Coreograph TMA dearray
  (`use_tma_dearray`).

- The TMA path. Each dearrayed core is processed on its own, then `MERGE_SPATIALDATA` merges
  the cores into one store per slide and `MERGE_REPORT` writes one QC page per slide,
  `{sample}_slide_report.html`.

- Resource profiles `size_tiny`, `size_small`, `size_medium` and `size_huge`, and
  `conf/slurm.config`.

- A container manifest (`tools/container_manifest.py`) and pre-staging instructions in
  [docs/containers.md](docs/containers.md).

- Tests: pytest, validation and stub nf-tests in CI, and two exemplar runs on the cluster (`tests/exemplar00{1,2}.nf.test`) with cell-count baselines.

- StarDist to `CITATIONS.md`.

- `PUBLISH_SPATIALDATA`, a publish sink whose only job is to copy the finished store into the
  output directory. `publishDir` is a process directive, so publishing a channel means declaring
  it as some process's output; aggregation and fluorescence annotation both write into the store
  and which runs last depends on `use_fluorescence_annotation`, so neither can own the
  publication. On the TMA path it runs after `MERGE_SPATIALDATA` and publishes the merged store
  only, once per slide. The per-core stores are no longer published, because the merged store
  copies every element family and every table out of them, prefixed by core.

- A metro map of the three paths that have been run on real data, in `docs/pipeline_paths.mmd`,
  rendered to SVG with [nf-metro](https://github.com/seqeralabs/nf-metro) and described in
  `docs/pipeline-paths.md`.

- Citations for the Leiden algorithm and python-igraph, which the QC report's clustering calls
  through `sc.tl.leiden(flavor="igraph")`.

- Project context (`CLAUDE.md`) and the phased plan (`ROADMAP.md`). The linting
  configuration that was proposed under `planning/` now lives in `.pre-commit-config.yaml`.

- Copyright notice alongside the retained nf-core/sopa notice in `LICENSE`, as MIT requires for
  derivative works.

- MCMICRO, BaSiC, ASHLAR, background_subtraction and Cellpose to `CITATIONS.md`.

- QC report, per sample. `QC_METRICS` writes every metric as machine-readable JSON, `QC_IMAGES`
  renders segmentation overlays and clusters the cells, and `QC_REPORT` renders both as one
  self-contained HTML file. Published to `<outdir>/qc`. `--use_qc` and `--use_qc_images` switch
  them; everything else is `ext.args` in `conf/modules.config`. See
  [docs/output.md](docs/output.md).

### Changed

- Imported the [nf-core/sopa](https://github.com/nf-core/sopa) `dev` tree at
  `c2b4e5fe1f5291a3f079e55859cd2f42e588e324` as the starting point for the downstream half, on an
  orphan branch with no inherited history. The import commit is deliberately unmodified so it can be
  verified against upstream.

- Rebranded to `josenimo/histo`: pipeline name, manifest, schema metadata, workflow identifiers
  (`SOPA` to `HISTO`, `NFCORE_SOPA` to `HISTO_PIPELINE`), startup banner, email templates, README,
  config headers, `modules.json` name and homepage, and the GitHub issue and PR templates. Module and
  subworkflow SHA pins in `modules.json` verified unchanged.

- Reset the version to `0.1.0dev`. The previous history in this file described nf-core/sopa's
  releases, which do not apply to this pipeline.

- Replaced the nf-core ASCII logo in the startup banner with a plain banner driven by
  `workflow.manifest`, so it cannot go stale.

- Rewrote `docs/usage.md` for mIF input. It documented sopa's samplesheet format for spatial
  transcriptomics platforms, none of which is in scope.

- Replaced `docs/CONTRIBUTING.md`'s nf-core community contribution process with pointers to
  `CLAUDE.md` and `AGENTS.md`, keeping the AI and LLM guidance.

- **Breaking.** The marker sheet moved from the `--marker_sheet` parameter to a required
  `marker_sheet` column in the samplesheet, one sheet per sample. The parameter is gone, and a
  samplesheet without the column fails at startup. A marker sheet describes a sample, and two
  samples in one run may have different channel layouts, which one parameter could not express.
  Every cycle row of a sample must name the same file, since the sheet describes the whole
  stitched image rather than one cycle of it. See [docs/usage.md](docs/usage.md).

- The marker sheet gained two columns. `channel_role` is required and is one of `dna`, `marker`,
  `autofluorescence` or `blank`; `channel_compartment` is optional and is `nuclear`, `cytoplasm`,
  `membrane` or a `+`-joined combination. They are separate columns because role decides control
  flow and compartment decides interpretation. Two checks arrive with them: every cycle needs at
  least one `dna` channel, and `background` must name a channel whose role is `autofluorescence`.
  QC finds the nuclear channel by `channel_role`, not by its name.

- backsub receives the marker sheet as written instead of a six-column rewrite. It reads the CSV
  with `pd.read_csv` and addresses columns by name, so columns it has no use for pass through into
  its own marker output. Dropping the rewrite is what allowed the sheet to become per sample: the
  rewrite produced one shared file.

- On the TMA path, Coreograph runs before background subtraction, so each core keeps a
  before-image and the QC report can compare before and after.

- `MERGE_SPATIALDATA` publishes only its manifest, from a selector in `conf/modules.config`
  rather than a `publishDir` in the module. The merged store itself is published by
  `PUBLISH_SPATIALDATA`, and the unfiltered directive this replaces also dropped a stray
  `versions.yml` in the output root.

### Fixed

- `ASHLAR` records `ashlar: stub` on a stub run instead of a blank. It captured its version with
  `eval("ashlar --version | sed 's/^.*ashlar //'")`, and the pipe meant the exit status was
  `sed`'s, so an absent `ashlar` produced a task that succeeded and wrote `ashlar:` with nothing
  after it into `histo_software_versions.yml`. A blank in a provenance file reads like a captured
  value, so this was a silent wrong answer rather than a visible gap. Patched the same way as
  `backsub`.

- The background subtraction path can be stub-run. `modules/nf-core/backsub` declared its version
  with `eval('backsub --version')`, and Nextflow evaluates an `eval` output even under `-stub`, so
  the task died with `bash: backsub: command not found` on any machine without the tool and that
  path had no stub coverage at all. Patched with `nf-core modules patch` to
  `eval(workflow.stubRun ? 'echo stub' : 'backsub --version')`, so a real run still fails loudly
  if the tool is missing while a stub run records `backsub: stub` like every other module.

- A samplesheet that repeats a `cycle_number` within a sample is rejected at startup. It was
  previously accepted, and since a cycle is identified by `sample` and `cycle_number` together, two
  such rows were the same cycle as far as the pipeline could tell: each cycle's BaSiCPy profile went
  to whichever image finished first, and the run reported success. Found on a real three-cycle run
  numbered 1, 2, 2. Gaps are rejected too, which `assets/schema_input_cycle.json` had promised in
  its `errorMessage` without anything enforcing it.

- Parameters the schema does not declare, and booleans given on the command line, now stop the run
  at startup. `use_use_tma_dearray = true` was previously accepted and ignored, and `--use_qc false`
  previously enabled QC: Nextflow reads the flag alone, sets it true and discards the `false` before
  any pipeline code runs, so the value cannot be recovered or corrected afterwards. `--use_qc=false`
  arrived as a truthy string. All three are rejected with a message naming the parameter, and for a
  misspelling, the parameter that was probably meant. Booleans belong in a params file; a bare flag
  switches one on. See [docs/usage.md](docs/usage.md).

- The marker sheet reached `SET_CHANNEL_NAMES` as a queue channel holding one item whenever
  background subtraction was off, so Nextflow paired it element-wise against the stores and stopped
  at the shorter of the two. A dearrayed slide with four cores had its channels named on one core
  while the other three never reached the rest of the pipeline, and the run reported success. With
  no marker sheet at all the same channel was empty and the process ran zero times, which made the
  entire downstream half do nothing and still exit 0. Marker sheets are now keyed per sample and
  joined, so neither shape can occur.

- `SET_CHANNEL_NAMES` no longer fails when `use_backsub` is true. It asked for the image element
  named after `meta.sample`, but `sopa convert` names the element after the file it converted, and
  backsub's output carries a `_backsub` suffix. The two agreed only when no step renamed the image,
  so the run died with `no image element 'sample'. Present: ['sample_backsub']`. The module now lets
  the script find the sole image element instead. Channel labels always came from the marker sheet,
  never from the filename, so only the lookup changes.

- BaSiCPy on `.czi` input. Bio-Formats defaults to `zeissczi.autostitch=true`, which merges a tile
  mosaic into a single stitched image before the field count, leaving BaSiC one field to fit from. It
  then either failed as single-sited or, with `-ie`, fitted a meaningless profile. The reader now
  passes `zeissczi.autostitch=false` and `zeissczi.attachments=false` for `.czi` input. This meant
  vendoring the container's `/opt/main.py` as `bin/basicpy_main.py` and patching
  `modules/nf-core/basicpy` to call it from `PATH`, recorded with `nf-core modules patch`. Verified
  on real `.czi` data.

### Removed

- `REPORT`, and with it `sopa report`'s `{sample}_analysis_summary.html` and the stray
  `versions.yml` its unfiltered `publishDir` dropped in the output root. Its cell counts, area
  distribution and per-channel intensity distributions are all in the QC report, which is
  self-contained and backed by a machine-readable JSON. Two figures are genuinely lost: the UMAP,
  and the spatial cell-annotation scatter, which only ever rendered under
  `use_fluorescence_annotation`. Its transcripts section had always returned `None` here.

- The `rm -r ${sdata_path}/.sopa_cache` that `REPORT` inherited from nf-core/sopa. Nextflow stages
  the store as a symlink, so the deletion reached back into a completed task's output and left it
  no longer matching what that task produced. The cache is 2.4 MB in a 57 MB store, reproducible
  from the store, and now ships with it. Nothing writes to the store after aggregation any more, so
  QC, `MERGE_SPATIALDATA` and `PUBLISH_SPATIALDATA` fan out from one channel instead of chaining
  through `REPORT` to avoid racing it.

- The `(planned)` markers on BaSiCPy, ASHLAR and background_subtraction in `CITATIONS.md`. All
  three have been wired in since the preprocessing half landed.

- The nf-core Zenodo DOI from the manifest and README. It belongs to nf-core/sopa and retaining it
  would have claimed another project's citation.

- nf-core organisation files: code of conduct, RO-Crate provenance metadata, and logos.

- nf-core organisation CI: AWS megatests, release announcements, and the triage, lint-fix, PR-comment
  and template-version bots. Kept `nf-test.yml`, `linting.yml` and `download_pipeline.yml`.

- The completion email's embedded logo, which was read from disk at runtime and would have thrown
  after the logo files were deleted.

- The `workflow.manifest.doi` interpolation from the citation footer, which called `.tokenize()`
  unguarded on a field the manifest no longer defines.

- `.devcontainer/`, which configured a GitHub Codespaces environment that is unused.

### Not yet done

- `use_preprocessing = false` and StarDist are tested by stub runs only, not on real data.

- Cellpose downloads its model weights at run time, so segmentation needs network access.

- H&E input. Only `ome_tif` mIF works today, which the manifest description now says.

- The pass-or-fail QC gate. The metrics and the report exist and `{sample}_qc.json` is the
  contract a gate would read; the thresholds need more than one dataset behind them.
