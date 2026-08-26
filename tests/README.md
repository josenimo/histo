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

## Real tests — minutes, containers required

The full chain on a small real dataset.

```bash
export HISTO_FIXTURE=/fast/AG_Coscia/$USER/HISTO/test3_fixture
bash tools/make_fixture_sheets.sh          # writes the two CSVs next to the images
export TMPDIR=/fast/AG_Coscia/$USER/tmp && mkdir -p "$TMPDIR"
export NXF_TEMP="$TMPDIR" NXF_OPTS="-Djava.io.tmpdir=$TMPDIR" NXF_OFFLINE=true

nf-test test tests/fixture.nf.test --profile test_fixture,singularity,size_tiny,slurm
```

`test_fixture` is repeated on the command line even though the test file declares it,
because a bare `--profile` **replaces** that directive rather than adding to it. Omit it
and the run fails with `Missing required parameter(s): input`, which does not mention
profiles at all.

Prefixing with `+` appends instead, which is what the CI action does:

```bash
nf-test test tests/fixture.nf.test --profile=+singularity,size_tiny,slurm
```

Either form works. The explicit list is the one verified on the cluster.

The temp variables are not optional on this cluster. `/tmp` on the login node is small
and shared, and a run that overruns it fails with `No space left on device` pointing at
a `/tmp/nxf-...` path, which reads like a quota problem and is not one.

`tools/make_fixture_sheets.sh` writes `samplesheet_fixture.csv` and `markers_fixture.csv` into
`$HISTO_FIXTURE`. Run it once after copying the fixture anywhere, and again after moving it. The
sheets are generated rather than committed because a samplesheet's paths are resolved against the
launch directory and must therefore be absolute, which makes them machine-specific — and because
the fixture itself lives outside this repository, so sheets committed here would describe a
directory that is not here either. The script is tracked; what it writes is not.

Relative paths look like they should avoid all of this and do not. nf-schema resolves a
samplesheet's path columns against `workflow.launchDir`, and nf-test gives every test its own
launch directory under `.nf-test/tests/<hash>/`, whose name changes whenever the test file is
edited. There is no directory the images could sit in.

**The fixture is not in this repository.** It is a 2×2 tile crop of exemplar001:
two cycles, two channels each, 1280×1080 tiles, uint16, 0.65 µm/px, about 43 MB. Git
keeps every version of a binary forever, so a fixture that size belongs in a separate
test-data repository fetched at test time, not here.

With `patch_width_pixel` around 1000 the ~2400×2000 stitched mosaic gives six patches,
which exercises boundary resolution rather than just running segmentation once.

Assert on properties that survive a version bump, not checksums:

- channel names exactly equal the marker sheet
- cell count within ±2% of a recorded baseline
- expected element names present in the Zarr
- one segmentation task per patch
- `versions.yml` names every process

Cellpose output shifts slightly with version and hardware, so a checksum snapshot of
segmentation results fails for reasons that do not matter.

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
