#!/usr/bin/env bash
# ==============================================================================
# Unified Test Matrix Runner for MCMICRO-SOPA Pipeline
# Covers Use Cases 1-4 both locally (Docker / Stub) and on HPC (Singularity / Slurm)
# ==============================================================================

set -e

PROFILE=${1:-"docker"} # Default profile: docker (or singularity, slurm, stub)
MODE=${2:-"full"}      # Mode: full or stub

echo "==================================================================="
echo " RUNNING MCMICRO-SOPA TEST SUITE"
echo " Profile : $PROFILE"
echo " Mode    : $MODE"
echo "==================================================================="

STUB_FLAG=""
if [ "$MODE" == "stub" ]; then
    STUB_FLAG="-stub"
fi

TEST_CASES=(
    "case0_sopa_direct.yaml"
    "case1_exemplar001_basic.yaml"
    "case2_exemplar001_illu.yaml"
    "case3_exemplar001_illu_backsub.yaml"
    "case4_exemplar002_tma_full.yaml"
)

for config in "${TEST_CASES[@]}"; do
    echo ""
    echo "-------------------------------------------------------------------"
    echo " Executing Test Case: $config"
    echo "-------------------------------------------------------------------"
    
    nextflow run main.nf \
        -profile "$PROFILE" \
        -params-file "tests/configs/$config" \
        $STUB_FLAG
        
    echo "[PASSED] Test Case $config completed successfully."
done

echo ""
echo "==================================================================="
echo " ALL TEST CASES PASSED SUCCESSFULLY!"
echo "==================================================================="
