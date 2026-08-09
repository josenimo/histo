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

### Fixed

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
