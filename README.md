# josenimo/histo

Processing, segmentation and quantification of multiplex immunofluorescence (mIF) images.
H&E is planned and not supported: `technology` accepts `ome_tif` only.

> [!WARNING]
> **Runs end to end, but is pre-release at `0.1.0dev`.** Both halves work on real data: mIF and TMA
> slides have been processed from raw cycles to a quantified SpatialData object. The input format is
> still changing and parameter names may still change. Every threshold in the QC report was
> calibrated against a single slide. Check your results.

[![Nextflow](https://img.shields.io/badge/version-%E2%89%A525.10.4-green?style=flat&logo=nextflow&logoColor=white&color=%230DC09D&link=https%3A%2F%2Fnextflow.io)](https://www.nextflow.io/)
[![nf-test](https://img.shields.io/badge/unit_tests-nf--test-337ab7.svg)](https://www.nf-test.com)
[![run with singularity](https://img.shields.io/badge/run%20with-singularity-1d355c.svg?labelColor=000000)](https://sylabs.io/docs/)

## What this is

A Nextflow pipeline for imaging data from human tissue, built to run unattended on datasets from
colleagues as well as my own. It combines two existing projects:

| Source                                                | What is taken from it                                                                                   |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| [nf-core/mcmicro](https://github.com/nf-core/mcmicro) | Preprocessing: illumination correction, stitching and registration, background subtraction, TMA dearray |
| [nf-core/sopa](https://github.com/nf-core/sopa)       | Everything from segmentation onward: SpatialData object, tiled segmentation, aggregation, reporting     |

The handoff between the two halves is a single stitched OME-TIFF.

sopa was chosen for the downstream half because its segmentation is **size independent**: it tiles
the image, segments each tile, and parallelises across an HPC cluster, backing everything with a
Zarr-based [SpatialData](https://github.com/scverse/spatialdata) object. Input images here run from
5 GB to 100 GB, so that property is the single most important capability in the design.

This is a **personal pipeline. It is not an nf-core pipeline** and is not affiliated with or
endorsed by the nf-core community. It follows nf-core conventions because they genuinely help with
reproducibility, and to keep open the option of contributing modules upstream later.

## Steps

Preprocessing, from nf-core/mcmicro:

1. Illumination correction (BaSiCPy)
2. Stitching and registration (Ashlar)
3. Background subtraction — optional, `--use_backsub`
4. TMA dearray (UNetCoreograph) — optional, `--use_tma_dearray`

Downstream, from nf-core/sopa:

5. Conversion to a SpatialData Zarr object
6. Channel naming from the marker sheet
7. Optional tissue segmentation, to skip empty tiles
8. Tiled cell segmentation with Cellpose or StarDist, parallelised per tile
9. Aggregation of channel intensities per cell
10. QC report, and for a TMA, a merged object per slide

## Usage

```bash
nextflow run josenimo/histo -r dev \
    -profile singularity,size_small,slurm \
    -params-file params.yml
```

See [docs/usage.md](docs/usage.md) for the samplesheet format, parameters and defaults,
[docs/output.md](docs/output.md) for what comes out, and [docs/containers.md](docs/containers.md)
for pre-staging images.

## What is likely to change

Expect breaking changes before `1.0.0`.

- **Resource profiles** are estimates apart from `size_tiny`, and will be rewritten from real runs.
- **Aggregation** currently reports mean intensity per cell; more per-cell metrics are being
  considered.
- **H&E support** is planned; only `ome_tif` mIF input works today.

Pixel size is deliberately **not** written into the Zarr: SpatialData's coordinate-system model is a
poor fit for it, so images stay in pixel units. Full reasoning and progress in
[ROADMAP.md](ROADMAP.md), which is where open work is tracked.

## Tests and checks

Six layers, cheapest and fastest first. Each catches a different class of problem, and
none of them substitutes for another.

| Layer                    | What it checks                      | Data          | Where             | Time    |
| ------------------------ | ----------------------------------- | ------------- | ----------------- | ------- |
| Pre-commit hooks         | Style, and repo-specific rules      | none          | Local commit + CI | seconds |
| `nf-core pipelines lint` | Template conformance                | none          | CI                | seconds |
| Unit tests               | Logic inside `bin/` and `tools/`    | none          | CI + local        | seconds |
| Validation tests         | That bad input is actually rejected | none          | CI + local        | seconds |
| Stub tests               | Channel topology                    | placeholders  | CI + local        | seconds |
| Pre-release, exemplar-001 | The WSI path, on real images       | 191 MB, fetched | Cluster, by hand | minutes |
| Pre-release, exemplar-002 | The TMA path with subtraction      | 635 MB, fetched | Cluster, by hand | minutes |

### Pre-commit hooks — `prek run --all-files`

Eighteen hooks. Twelve are off-the-shelf: `prettier`, whitespace and end-of-file fixers,
`check-merge-conflict`, `detect-private-key`, `check-added-large-files`, the two shebang
consistency hooks, `nextflow-lint`, `shellcheck`, and `ruff-check`/`ruff-format` over `bin/`,
`tools/` and `tests/unit/`.

Six are written for this repository, each after a real defect:

| Hook                             | Catches                                                               |
| -------------------------------- | --------------------------------------------------------------------- |
| `no-absolute-container-paths`    | A cluster `.sif` path hardcoded in a module instead of a registry URI |
| `no-nested-container-invocation` | `docker run` from inside a process — Nextflow manages containers      |
| `no-eager-image-reads`           | `tifffile.imread` on a 100 GB image; reads must be lazy               |
| `module-has-stub`                | A module that creates a file but has no `stub:` block                 |
| `module-emits-versions`          | A module that records no tool version                                 |
| `stub-drift`                     | An `output:` block that changed while its `stub:` did not             |

`stub-drift` is the important one: it targets the failure mode where the _test_ passes and
the real run fails, which is worse than having no test.

### Unit tests — `pytest tests/unit`

159 tests over the pure logic in `bin/` and `tools/`: marker sheet parsing, channel-label
reading, TMA core naming, table region relinking, QC metrics and report rendering, container
cache filenames. No containers, no imaging data, no Nextflow.

### Validation tests — `nf-test test --tag validation`

29 cases over the functions that reject bad input, run as `nextflow_function` tests so no
process starts. Twelve of them watch a check reject something and assert on the message text,
because a check never seen failing is not known to work and one that fires with an unreadable
message is half a check.

What they cover: a marker sheet with a cycle missing its nuclear stain, a repeated marker
name, a `background` column pointing at the wrong kind of channel, a sample whose cycles name
different marker sheets, a repeated or gapped `cycle_number`, a misspelt parameter, and a
boolean set on the command line in either of the two forms that do not work.

### Stub tests — `nf-test test --tag stub`

Runs the preprocessing and QC subworkflows with `-stub`, so no tool executes. Asserts wiring
only: that two cycles group into one image, that a TMA fans out into cores which keep their
slide identity and carry no file extension in their IDs, that each core inherits its slide's
marker sheet, and that the optional QC inputs can each be absent without silently removing
the report.

Inputs are a few hundred bytes of placeholder in `tests/stub_data/` — stub runs stage their
inputs and never read them.

### Pre-release tests — cluster only, two of them

```bash
export HISTO_EXEMPLARS=/path/to/exemplars
bash tools/fetch_exemplars.sh

nf-test test tests/exemplar001.nf.test --profile test_exemplar001,singularity,size_small,slurm
nf-test test tests/exemplar002.nf.test --profile test_exemplar002,singularity,size_small,slurm
```

Between them they cover every path the pipeline has. **exemplar-001** is three mIF cycles on a
whole slide — BaSiCPy, Ashlar, tiled segmentation, no subtraction or dearray. **exemplar-002** is
a two-cycle TMA with background subtraction, which adds Coreograph, per-core subtraction, the
merge back into one store and the slide-level report. exemplar-002 is used for that because its
cycle 2 holds real autofluorescence channels, which is rare in public data and better than
relabelling a marker to stand in for one.

`tools/fetch_exemplars.sh` downloads the images from the public mcmicro S3 bucket — the same
datasets mcmicro's own tutorial uses, no credentials — taking only the cycles the tests need.
The marker sheets are ours and are committed in `tests/exemplar_data/`, because the published
ones carry no `channel_role` and exemplar-002's has no `exposure` or `background` either. The
samplesheets are generated by the same script, since nf-schema resolves their paths against the
launch directory and nf-test gives every test a different one.

**Not in CI, on purpose.** The images come to about 8.8 GB on disk for the mIF path and 14.7 GB
with Coreograph, against roughly 14 GB free on a GitHub-hosted runner and a 10 GB cache quota,
re-pulled every run. nf-core reaches the same conclusion and runs its full tests on AWS at
release; this does the same with a cluster and a person.

Assertions are properties rather than checksums — Cellpose output shifts with version and
hardware. Cell-count baselines are not recorded yet and their assertions are commented out,
waiting for a real run rather than a number guessed in advance.

### Also in CI

`download_pipeline.yml` counts container images before and after a stub run and fails if the
count changed. It is the only automated guard that nothing is pulled at launch time, which
matters because the cluster cannot be relied on to reach a registry mid-run.

### Not yet covered

There is no test for the TMA path on real data and none for background subtraction. Both have
wiring coverage under `-stub` and have been run by hand on the cluster, but nothing automated
asserts on their numbers.

`tests/default.nf.test` used to be an inherited nf-core/sopa snapshot describing outputs this
pipeline no longer produces. It is now a property-based stub test of the
`use_preprocessing = false` entry point. `tests/cellpose.nf.test` was the same kind of
inherited snapshot and was removed rather than rewritten: `-profile test` already covers that
path, so a second file asserting the same wiring earned nothing.

## Credits

Written by Jose Nimo at the Max Delbrück Center for Molecular Medicine, Berlin.

This pipeline is derived from two MIT licensed projects and would not exist without them:

- **nf-core/sopa**, written by [Quentin Blampey](https://github.com/quentinblampey) and
  contributors. The downstream half of this pipeline is derived from it, and many modules are
  vendored from it with their original licence headers and source commits recorded.
- **nf-core/mcmicro**, from the Laboratory of Systems Pharmacology and the nf-core community.

See [`CITATIONS.md`](CITATIONS.md) for the full list of tools and their references.

## Citations

**This pipeline has no DOI and should not be cited in place of the tools it wraps.** If you use it,
cite the underlying tools. The two most important:

> **Sopa: a technology-invariant pipeline for analyses of image-based spatial omics.**
>
> Quentin Blampey, Kevin Mulder, Margaux Gardet, Stergios Christodoulidis, Charles-Antoine Dutertre,
> Fabrice André, Florent Ginhoux & Paul-Henry Cournède.
>
> _Nat Commun._ 2024 June 11. doi: [10.1038/s41467-024-48981-z](https://doi.org/10.1038/s41467-024-48981-z)

> **The nf-core framework for community-curated bioinformatics pipelines.**
>
> Philip Ewels, Alexander Peltzer, Sven Fillinger, Harshil Patel, Johannes Alneberg, Andreas Wilm,
> Maxime Ulysse Garcia, Paolo Di Tommaso & Sven Nahnsen.
>
> _Nat Biotechnol._ 2020 Feb 13. doi: [10.1038/s41587-020-0439-x](https://dx.doi.org/10.1038/s41587-020-0439-x)

## Licence

MIT. See [`LICENSE`](LICENSE).
