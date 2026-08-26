# Tests

Four tiers, cheapest first.

## Unit tests — seconds, no containers

Pure Python over the logic in `bin/` and `tools/`: marker sheet parsing, core naming,
table relinking, QC metrics and report rendering, container cache filenames.

```bash
pytest tests/unit
```

Runs in CI on every push (`.github/workflows/unit-tests.yml`).

## Validation tests — seconds, no containers, no Nextflow processes

The functions that reject bad input, called directly as `nextflow_function` tests.

```bash
nf-test test --tag validation
```

Most of these assert on a rejection and on the wording of the message. That is
deliberate: a check nobody has watched fail is not known to work, and one that fires
with an unreadable message is half a check. `docs/decisions.md` records why, under
Recurring lessons.

## Stub tests — seconds, no containers, no real data

Channel topology. No tool runs, so these say nothing about whether an image was
stitched well — they catch cycles grouped wrongly, a TMA fan-out that loses core
identity, a marker sheet that reaches one sample out of four, an emit nothing
consumes.

```bash
nf-test test --tag stub
```

`tests/stub_data/` holds a few hundred bytes of placeholder standing in for images.
Stub runs stage their inputs and never read them, so existence is all that is needed,
and this keeps tens of megabytes out of the repository's permanent history.

Requires `-profile laptop`, already set in the test file: `ashlar` and `backsub`
declare versions with `eval()`, which Nextflow evaluates in the task environment even
under `-stub`, so `tests/stub_bin` must be on PATH.

CI runs `--tag stub,validation`, which is both of the tiers above and nothing else.
Neither needs a container, which is why they fit on an ordinary GitHub runner.

Until 2026-08-26 that sentence was false. `nf-test.yml` requested self-hosted runners
using labels inherited from the nf-core template, nothing in this repository provides
them, and so every run sat queued indefinitely and the matrix was skipped. The tiers
had never run in CI. `gh run list` showed it plainly once anyone looked: every "Run
nf-test" with a blank conclusion, going back as far as the history goes.

## Pre-release tests — the cluster, by hand, two of them

Real pixels through the whole chain. Not in CI, and that is a decision with numbers
behind it rather than a gap: the container images come to about 8.8 GB on disk for the
mIF path and 14.7 GB with Coreograph, against roughly 14 GB free on a GitHub-hosted
runner and a 10 GB cache quota, re-pulled every run. nf-core reaches the same
conclusion and runs its full tests on AWS at release time; this does the same thing
with a cluster and a person.

Between them the two cover every path the pipeline has.

| | exemplar-001 | exemplar-002 |
| --- | --- | --- |
| covers | mIF slide, whole-slide | TMA, dearrayed |
| cycles | 6, 7, 8 — 12 channels | 1, 2 — 8 channels |
| backsub | no | **yes**, real autofluorescence channels |
| also exercises | BaSiCPy, Ashlar, tiled segmentation | Coreograph, per-core subtraction, merge, slide report |
| download | 191 MB | 635 MB |

```bash
export HISTO_EXEMPLARS=/fast/AG_Coscia/$USER/HISTO/exemplars
bash tools/fetch_exemplars.sh

export TMPDIR=/fast/AG_Coscia/$USER/tmp && mkdir -p "$TMPDIR"
export NXF_TEMP="$TMPDIR" NXF_OPTS="-Djava.io.tmpdir=$TMPDIR" NXF_OFFLINE=true

nf-test test tests/exemplar001.nf.test --profile test_exemplar001,singularity,size_small,slurm
nf-test test tests/exemplar002.nf.test --profile test_exemplar002,singularity,size_small,slurm
```

The profile name is repeated on the command line even though each test file declares
it, because a bare `--profile` **replaces** that directive rather than adding to it.
Omit it and the run fails with `Missing required parameter(s): input`, which does not
mention profiles at all. Prefixing with `+` appends instead:
`--profile=+singularity,size_small,slurm`.

The temp variables are not optional on this cluster. `/tmp` on the login node is small
and shared, and a run that overruns it fails with `No space left on device` pointing at
a `/tmp/nxf-...` path, which reads like a quota problem and is not one.

### Where the data comes from

`tools/fetch_exemplars.sh` pulls the images from the public mcmicro S3 bucket — the same
datasets mcmicro's own tutorial uses, no credentials — and takes only the cycles the
tests need rather than all ten. It skips files already present at the right size, so an
interrupted download resumes. Run it somewhere with internet and copy the directory
across if the cluster has no outbound access.

**The marker sheets are ours and are committed**, in `tests/exemplar_data/`. mcmicro's
published `markers.csv` cannot be used: it has no `channel_role`, which this pipeline
requires, and exemplar-002's has no `exposure` or `background` columns at all, which
backsub needs. The sheets here add those and nothing else — the channel names, cycles
and wavelengths match the published ones.

**The samplesheets are generated**, by the same script, because they cannot be
committed. nf-schema resolves a samplesheet's path columns against `workflow.launchDir`,
and nf-test gives every test its own launch directory under `.nf-test/tests/<hash>/`
whose name changes whenever the test file is edited — so a relative path reaches nothing
and an absolute one is machine-specific. Generating them is the only arrangement that
works from a clone.

### Baselines are not recorded yet

Both tests assert only that segmentation produced cells. The cell-count windows are
commented out, waiting for a real run to supply the numbers, because a baseline invented
in advance is not a baseline — it is a guess the first run gets judged against. Fill them
in from the first green run.

What is asserted now: channel names exactly matching the sheet, core count on the TMA,
which processes ran and how many times, the nuclear stain having been chosen by
`channel_role` rather than by a name pattern, the before-and-after subtraction block
being present on every core, background channels not having moved under subtraction, and
`versions.yml` naming every process.

Assertions are properties rather than checksums throughout. Cellpose output shifts with
version and hardware, so a snapshot of segmentation results fails for reasons that have
nothing to do with this pipeline.

## The pre-stitched entry point — `nf-test test tests/default.nf.test`

`-profile test` under `-stub`: images arriving already stitched, so `BASICPY`, `ASHLAR` and
`SET_CHANNEL_NAMES` never run. Asserts that they do not, that segmentation still tiles into two
patches, that neither slide-level step appears on a non-TMA run, and that all three QC steps do.

This replaced an inherited nf-core/sopa snapshot that recorded `"nf-core/sopa": "v1.0.1"` and
asserted on `explorer` and `sopa_software_versions`, outputs this pipeline does not produce. It
could not pass and had not been run in a long time, which is worse than having no test: it
occupied the place where a real one would go. `cellpose.nf.test` was the same and was deleted
rather than rewritten, since `-profile test` already covers that wiring.

The file has to keep its name: `nf-core pipelines lint` checks that `tests/default.nf.test`
exists, and deleting it fails the release lint.
