#!/usr/bin/env bash
#
# Write the two CSVs the fixture test needs, next to the fixture's images.
#
# The fixture is ~43 MB of binary and lives outside this repository, so the sheets
# that describe it cannot be committed here either -- and a samplesheet's paths are
# resolved against the launch directory, so they have to be absolute and therefore
# machine-specific. That is why this is a generator rather than two checked-in files:
# the script is tracked, the sheets it writes are not, and the fixture directory
# needs to hold nothing but the two images.
#
#     export HISTO_FIXTURE=/fast/AG_Coscia/$USER/HISTO/test3_fixture
#     bash tools/make_fixture_sheets.sh
#     nf-test test tests/fixture.nf.test --profile test_fixture,singularity,size_tiny,slurm
#
# Re-run it after moving or copying the fixture. It only rewrites the CSVs, so it is
# safe to run repeatedly.
#
# Why relative paths are not an option, since it looks like they should be: nf-schema
# resolves a samplesheet's path columns against workflow.launchDir, and nf-test gives
# every test its own launch directory under .nf-test/tests/<hash>/ whose name changes
# whenever the test file is edited. There is no directory the images could sit in.
set -euo pipefail

if [[ -z "${HISTO_FIXTURE:-}" ]]; then
    echo "HISTO_FIXTURE is not set. Point it at the directory holding the fixture images:" >&2
    echo "  export HISTO_FIXTURE=/fast/AG_Coscia/\$USER/HISTO/test3_fixture" >&2
    exit 1
fi

# Resolve to an absolute path without requiring realpath, which macOS lacks by default.
fixture="$(cd "$HISTO_FIXTURE" 2>/dev/null && pwd)" || {
    echo "HISTO_FIXTURE points at '${HISTO_FIXTURE}', which is not a directory." >&2
    exit 1
}

cycle1="$fixture/exemplar-001-cycle-06.ome.tiff"
cycle2="$fixture/exemplar-001-cycle-07.ome.tiff"
for f in "$cycle1" "$cycle2"; do
    if [[ ! -f "$f" ]]; then
        echo "Missing fixture image: $f" >&2
        echo "The fixture is a 2x2 tile crop of exemplar001, two cycles of two channels." >&2
        exit 1
    fi
done

markers="$fixture/markers_fixture.csv"

# One row per channel, counted continuously across both cycles. channel_role is
# required and is what identifies the nuclear stain: these are called DNA_6 and DNA_7
# rather than DAPI, which is exactly the case that used to be found by name matching
# and is not any more.
cat > "$markers" <<'CSV'
channel_number,cycle_number,marker_name,channel_role,channel_compartment,filter,excitation_wavelength,emission_wavelength
1,1,DNA_6,dna,nuclear,DAPI,395,431
2,1,ELANE,marker,cytoplasm,FITC,485,525
3,2,DNA_7,dna,nuclear,DAPI,395,431
4,2,CD11B,marker,cytoplasm,FITC,485,525
CSV

# `sample` must stay exemplar-001: tests/fixture.nf.test asserts on the path
# $outputDir/exemplar-001.zarr, which is named after it.
cat > "$fixture/samplesheet_fixture.csv" <<CSV
sample,cycle_number,image_tiles,marker_sheet
exemplar-001,1,$cycle1,$markers
exemplar-001,2,$cycle2,$markers
CSV

echo "wrote $fixture/samplesheet_fixture.csv"
echo "wrote $markers"
