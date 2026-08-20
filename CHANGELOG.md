# josenimo/histo: Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## v0.1.0dev - unreleased

Initial scaffold. Not yet runnable; see [ROADMAP.md](ROADMAP.md).

### Added

- Project context (`AGENT_CONTEXT.md`), phased plan (`ROADMAP.md`), and proposed linting
  configuration under `planning/`.
- `create_issues.sh`, which publishes the roadmap as GitHub milestones and issues.
- Copyright notice alongside the retained nf-core/sopa notice in `LICENSE`, as MIT requires for
  derivative works.
- MCMICRO, BaSiC, ASHLAR, background_subtraction and Cellpose to `CITATIONS.md`.

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
- Emptied `docs/usage.md` rather than rebranding it. It documented sopa's samplesheet format for
  spatial transcriptomics platforms, none of which is in scope, and the mIF input format is undecided.
- Replaced `docs/CONTRIBUTING.md`'s nf-core community contribution process with pointers to
  `AGENT_CONTEXT.md` and `AGENTS.md`, keeping the AI and LLM guidance.

### Removed

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

### Added

- QC report, per sample. `QC_METRICS` writes every metric as machine-readable JSON, `QC_IMAGES`
  renders segmentation overlays and clusters the cells, and `QC_REPORT` renders both as one
  self-contained HTML file. Published to `<outdir>/qc`. `--use_qc` and `--use_qc_images` switch
  them; everything else is `ext.args` in `conf/modules.config`. See
  [docs/output.md](docs/output.md).

### Changed

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
  The QC scripts still find the nuclear channel by matching its name; `channel_role` replaces that
  next.

- backsub receives the marker sheet as written instead of a six-column rewrite. It reads the CSV
  with `pd.read_csv` and addresses columns by name, so columns it has no use for pass through into
  its own marker output. Dropping the rewrite is what allowed the sheet to become per sample: the
  rewrite produced one shared file.

### Fixed

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

### Known broken

- `tests/*.nf.test.snap` still record `"nf-core/sopa": "v1.0.1"`. Snapshots must not be hand-edited;
  they need regenerating with `nf-test`, which needs real containers on the cluster. Until then
  `nf-test` fails. This blocks the Phase 1 exit criterion.
- `nf-core pipelines lint` has not been run since `is_nfcore` was set to `false`. Expect failures.
- `nextflow_schema.json` and `modules.json` were hand-edited for metadata only. Confirm with
  `nf-core pipelines schema build`.

### Not yet done

The preprocessing half does not exist. The downstream half still contains sopa's transcriptomics
paths (baysor, comseg, proseg, stardist, Space Ranger, transcript patches) pending removal, along
with their test configs and snapshots.
