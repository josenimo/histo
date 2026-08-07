# Tests

Three tiers, cheapest first.

## Unit tests — seconds, no containers

Pure Python over the logic in `bin/` and `tools/`: marker sheet parsing, core naming,
table relinking, container cache filenames.

```bash
pytest tests/unit
```

Runs in CI on every push (`.github/workflows/unit-tests.yml`).

## Stub tests — seconds, no containers, no real data

Channel topology. No tool runs, so these say nothing about whether an image was
stitched well — they catch cycles grouped wrongly, a TMA fan-out that loses core
identity, an emit nothing consumes.

```bash
nf-test test tests/preprocess_images.nf.test
```

`tests/stub_data/` holds a few hundred bytes of placeholder standing in for images.
Stub runs stage their inputs and never read them, so existence is all that is needed,
and this keeps tens of megabytes out of the repository's permanent history.

Requires `-profile laptop`, already set in the test file: `ashlar` and `backsub`
declare versions with `eval()`, which Nextflow evaluates in the task environment even
under `-stub`, so `tests/stub_bin` must be on PATH.

## Real tests — minutes, containers required

The full chain on a small real dataset.

```bash
export HISTO_FIXTURE=/fast/AG_Coscia/$USER/HISTO/test3_fixture
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

## Inherited, currently stale

`default.nf.test` and `cellpose.nf.test` came from nf-core/sopa. Their snapshots still
record `"nf-core/sopa": "v1.0.1"` and describe outputs this pipeline no longer produces.
Regenerate with `nf-test test --update-snapshot` on the same architecture as CI, once
containers are available. Do not hand-edit them.
