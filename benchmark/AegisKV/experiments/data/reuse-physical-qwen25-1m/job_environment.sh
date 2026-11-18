#!/bin/bash
# Source before Python or here-documents: DGX /tmp was full in job 74263.
# Use only this task's private directory on the shared project/home volume.
: "${TASK_DIR:?TASK_DIR must identify the experiment directory}"
: "${SLURM_JOB_ID:?Run through Slurm}"
export TMPDIR="$TASK_DIR/tmp/$SLURM_JOB_ID"
mkdir -p "$TMPDIR"
chmod 700 "$TMPDIR"
export TMP="$TMPDIR" TEMP="$TMPDIR"
export TORCH_EXTENSIONS_DIR="$TMPDIR/torch_extensions"
export TRITON_CACHE_DIR="$TMPDIR/triton"
export CUDA_CACHE_PATH="$TMPDIR/cuda_cache"
export PYTHONUNBUFFERED=1
df -h "$TMPDIR"
df -i "$TMPDIR"
