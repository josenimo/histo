#!/usr/bin/env bash
#SBATCH --job-name=mcmicro_sopa
#SBATCH --output=logs/pipeline_%j.log
#SBATCH --error=logs/pipeline_%j.err
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8GB

# Load required HPC modules (adjust module names according to your HPC cluster)
module load java singularity nextflow 2>/dev/null || true

# Ensure logs directory exists
mkdir -p logs

# Environment variables for HPC singularity & caching
export NXF_SINGULARITY_CACHEDIR="$PWD/singularity_cache"
export SINGULARITY_CACHEDIR="$PWD/singularity_cache"
export CELLPOSE_LOCAL_MODELS_PATH="$PWD/cellpose_cache"
export NUMBA_CACHE_DIR="/tmp"
export MPLCONFIGDIR="/tmp"

mkdir -p "$NXF_SINGULARITY_CACHEDIR" "$CELLPOSE_LOCAL_MODELS_PATH"

CONFIG_FILE=${1:-"tests/configs/case4_exemplar002_tma_full.yaml"}

echo "==================================================================="
echo " SUBMITTING MCMICRO-SOPA TO SLURM HPC"
echo " Config: $CONFIG_FILE"
echo "==================================================================="

# Run Nextflow pipeline in SLURM + Singularity mode
nextflow run main.nf \
    -profile "singularity,slurm" \
    -params-file "$CONFIG_FILE" \
    -resume
