#!/usr/bin/env bash
# Run UNetCoreograph 2.4.6 on single cycle 01 of exemplar-002,
# apply bin/fix_core_ome_tiff.py, and verify with paquo (QuPath).
set -euo pipefail

CONTAINER="labsyspharm/unetcoreograph:2.4.6"
INPUT_IMAGE="/workspace/datasets/exemplar-002/raw/exemplar-002-cycle-01.ome.tiff"
OUTPUT_DIR="/workspace/results/coreograph_single_cycle"

rm -rf ./results/coreograph_single_cycle
mkdir -p ./results/coreograph_single_cycle

echo "Step 1: Running UNetCoreograph v2.4.6 container with DNA channel (--channel 0)..."
docker run --rm \
    -e PYTHONUNBUFFERED=1 \
    -v "$PWD:/workspace" \
    -w "/workspace" \
    "$CONTAINER" \
    python3 -u /app/UNetCoreograph.py \
    --imagePath "$INPUT_IMAGE" \
    --outputPath "$OUTPUT_DIR" \
    --channel 0 \
    --downsampleFactor 6 \
    --buffer 2

echo ""
echo "Step 2: Applying bin/fix_core_ome_tiff.py to format OME-TIFF metadata..."
uv run python bin/fix_core_ome_tiff.py ./results/coreograph_single_cycle

echo ""
echo "Step 3: Verifying QuPath metadata for all dearrayed core TIFFs using paquo..."
PAQUO_QUPATH_DIR="/Applications/QuPath-0.7.0-arm64.app" \
JAVA_HOME="/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home" \
uv run python bin/check_qupath_paquo.py ./results/coreograph_single_cycle
