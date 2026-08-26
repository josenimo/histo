#!/usr/bin/env bash
#
# Fetch the two exemplar datasets the pre-release checks run on, and write the
# samplesheets that point at them.
#
#     export HISTO_EXEMPLARS=/fast/AG_Coscia/$USER/HISTO/exemplars
#     bash tools/fetch_exemplars.sh
#
# Downloads about 826 MB from the public mcmicro S3 bucket, no credentials. Only
# the cycles the tests use, not the whole ten-cycle sets:
#
#   exemplar-001 cycles 6, 7, 8    191 MB   mIF slide, the WSI check
#   exemplar-002 cycles 1, 2       635 MB   TMA, the dearray and backsub check
#
# Run it on a machine with internet and copy the directory to the cluster, or run
# it on a login node if that one has outbound access. Re-running skips files that
# are already the right size, so an interrupted download resumes cheaply.
#
# It also writes the samplesheets, because they cannot be committed. nf-schema
# resolves a samplesheet's path columns against the launch directory, and nf-test
# gives every test its own launch directory named after a hash of the test file, so
# a relative path reaches nothing and an absolute one is machine-specific. Writing
# them here is the only arrangement that works from a clone.
#
# The marker sheets ARE committed, in tests/exemplar_data/. They are ours rather
# than mcmicro's: the published markers.csv has no channel_role, which this pipeline
# requires, and no exposure values, which backsub needs.
set -euo pipefail

BUCKET="https://mcmicro.s3.amazonaws.com/exemplars"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHEETS="$REPO/tests/exemplar_data"

if [[ -z "${HISTO_EXEMPLARS:-}" ]]; then
    echo "HISTO_EXEMPLARS is not set. Point it at a directory to download into:" >&2
    echo "  export HISTO_EXEMPLARS=/fast/AG_Coscia/\$USER/HISTO/exemplars" >&2
    exit 1
fi

mkdir -p "$HISTO_EXEMPLARS"
dest="$(cd "$HISTO_EXEMPLARS" && pwd)"

fetch() {
    local url="$1" out="$2"
    # Compare against the remote length rather than just testing existence, so a
    # half-written file from an interrupted run is replaced instead of trusted.
    local remote
    remote="$(curl -fsIL --max-time 60 "$url" | awk 'BEGIN{IGNORECASE=1}/^content-length:/{v=$2} END{print v+0}' | tr -d '\r')"
    if [[ -f "$out" ]]; then
        local have
        have="$(wc -c < "$out" | tr -d ' ')"
        if [[ "$have" == "$remote" && "$remote" != "0" ]]; then
            printf '  have  %s\n' "$(basename "$out")"
            return
        fi
    fi
    printf '  get   %s (%s MB)\n' "$(basename "$out")" "$((remote / 1048576))"
    curl -fL --max-time 3600 --retry 3 --retry-delay 5 -o "$out.part" "$url"
    mv "$out.part" "$out"
}

echo "exemplar-001, cycles 6-8, into $dest"
mkdir -p "$dest/exemplar-001"
for c in 06 07 08; do
    fetch "$BUCKET/001/exemplar-001/raw/exemplar-001-cycle-$c.ome.tiff" \
          "$dest/exemplar-001/exemplar-001-cycle-$c.ome.tiff"
done

echo "exemplar-002, cycles 1-2, into $dest"
mkdir -p "$dest/exemplar-002"
for c in 01 02; do
    fetch "$BUCKET/002/exemplar-002/raw/exemplar-002-cycle-$c.ome.tiff" \
          "$dest/exemplar-002/exemplar-002-cycle-$c.ome.tiff"
done

# cycle_number runs 1..N without gaps, which the pipeline enforces, so exemplar-001's
# cycles 6, 7 and 8 are numbered 1, 2 and 3 here. The marker names keep the original
# numbering -- DNA_6, DNA_7, DNA_8 -- so the sheet still says which acquisition each
# channel came from.
cat > "$dest/samplesheet_exemplar001.csv" <<CSV
sample,cycle_number,image_tiles,marker_sheet
exemplar-001,1,$dest/exemplar-001/exemplar-001-cycle-06.ome.tiff,$SHEETS/markers_exemplar001.csv
exemplar-001,2,$dest/exemplar-001/exemplar-001-cycle-07.ome.tiff,$SHEETS/markers_exemplar001.csv
exemplar-001,3,$dest/exemplar-001/exemplar-001-cycle-08.ome.tiff,$SHEETS/markers_exemplar001.csv
CSV

cat > "$dest/samplesheet_exemplar002.csv" <<CSV
sample,cycle_number,image_tiles,marker_sheet
exemplar-002,1,$dest/exemplar-002/exemplar-002-cycle-01.ome.tiff,$SHEETS/markers_exemplar002.csv
exemplar-002,2,$dest/exemplar-002/exemplar-002-cycle-02.ome.tiff,$SHEETS/markers_exemplar002.csv
CSV

echo
echo "wrote $dest/samplesheet_exemplar001.csv"
echo "wrote $dest/samplesheet_exemplar002.csv"
echo
echo "Now, on the cluster:"
echo "  nf-test test tests/exemplar001.nf.test --profile test_exemplar001,singularity,size_small,slurm"
echo "  nf-test test tests/exemplar002.nf.test --profile test_exemplar002,singularity,size_small,slurm"
