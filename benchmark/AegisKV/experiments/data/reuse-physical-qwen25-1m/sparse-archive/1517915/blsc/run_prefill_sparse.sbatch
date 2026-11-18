#!/bin/bash
# Resource/time requests are supplied only by budget_submit.py.
set -euo pipefail
: "${AEGIS_ROOT:?Use budget_submit.py after CPU preparation}"
: "${AEGIS_PYTHON:?Missing verified isolated environment}"
: "${AEGIS_MODEL:?Missing verified official 1M model}"
TASK_DIR="$AEGIS_ROOT"
cd "$TASK_DIR"
source "$TASK_DIR/job_environment.sh"
OUT_DIR="$TASK_DIR/blsc/results/$SLURM_JOB_ID"
mkdir -p "$OUT_DIR"
AEGIS_WORKER_PID=""
stop_sparse_worker() {
  date -Iseconds > "$OUT_DIR/terminated-at.txt"
  if [[ -n "$AEGIS_WORKER_PID" ]]; then
    kill -TERM -- "-$AEGIS_WORKER_PID" 2>/dev/null || true
    wait "$AEGIS_WORKER_PID" 2>/dev/null || true
  fi
  exit 124
}
trap stop_sparse_worker TERM INT
cleanup_sparse_kv() {
  if [[ -n "${AEGIS_SHARED_FS:-}" ]]; then
    python3 "$TASK_DIR/blsc/cleanup_sharedfs.py" --job-id "$SLURM_JOB_ID" --batch-finalizer
  fi
}
trap cleanup_sparse_kv EXIT
AEGIS_STORAGE_ARGS=()
if [[ -n "${AEGIS_SHARED_FS:-}" ]]; then
  mkdir -p "$AEGIS_SHARED_FS"
  python3 "$TASK_DIR/sharedfs_io.py" --probe-directory "$AEGIS_SHARED_FS" \
    --output "$OUT_DIR/sharedfs-compute-preflight.json"
  AEGIS_STORAGE_ARGS=(--sharedfs-root "$AEGIS_SHARED_FS")
fi
export OMP_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 NCCL_DEBUG=WARN
export CUDA_HOME="$TASK_DIR/setup/cuda-12.8"
export CUDA_PATH="$CUDA_HOME"
export CPATH="$CUDA_HOME/include"
for AEGIS_NVIDIA_INCLUDE in /home/bingxing2/home/scx8q31/miniconda3/envs/megatron-reft/lib/python3.12/site-packages/nvidia/*/include; do
  if [ -d "$AEGIS_NVIDIA_INCLUDE" ]; then CPATH="$CPATH:$AEGIS_NVIDIA_INCLUDE"; fi
done
export C_INCLUDE_PATH="$CPATH" CPLUS_INCLUDE_PATH="$CPATH"
export LIBRARY_PATH="$CUDA_HOME/lib"
export PATH="$TASK_DIR/.venv/bin:$CUDA_HOME/bin:$PATH"
export FLASHINFER_CUDA_ARCH_LIST="8.0"
export FLASHINFER_WORKSPACE_BASE="$TASK_DIR/setup/flashinfer"
export TRITON_CACHE_DIR="$TASK_DIR/setup/triton"
# Reject incompatible allocations before expensive Torch imports/model loading.
AEGIS_DRIVER_MODE=$(python3 "$TASK_DIR/blsc/driver_check.py" --gpus "$TP" --output "$OUT_DIR/driver-check.json")
if [[ -n "${AEGIS_REQUIRE_GPU_NAME:-}" ]]; then
  python3 - "$OUT_DIR/driver-check.json" "$AEGIS_REQUIRE_GPU_NAME" <<'PY'
import json, sys
devices = json.load(open(sys.argv[1]))['devices']
assert all(d[0].strip() == sys.argv[2] for d in devices), devices
PY
fi
AEGIS_COMPAT_LIB=/home/bingxing2/home/scx8q31/apps/cuda-compat-12.8/lib
AEGIS_NATIVE_LD=""
IFS=: read -r -a AEGIS_LD_PARTS <<< "${LD_LIBRARY_PATH:-}"
for AEGIS_LD_PART in "${AEGIS_LD_PARTS[@]}"; do
  if [[ -n "$AEGIS_LD_PART" && "$AEGIS_LD_PART" != *cuda-compat* ]]; then
    AEGIS_NATIVE_LD="${AEGIS_NATIVE_LD:+$AEGIS_NATIVE_LD:}$AEGIS_LD_PART"
  fi
done
export LD_LIBRARY_PATH="$CUDA_HOME/lib${AEGIS_NATIVE_LD:+:$AEGIS_NATIVE_LD}"
if [ "$AEGIS_DRIVER_MODE" = compat ]; then export LD_LIBRARY_PATH="$AEGIS_COMPAT_LIB:$LD_LIBRARY_PATH"; fi
python3 "$TASK_DIR/blsc/driver_check.py" --gpus "$TP" --cuda-init --output "$OUT_DIR/cuda-init-check.json"
nvidia-smi -q > "$OUT_DIR/nvidia-smi-before.txt"
nvidia-smi topo -m > "$OUT_DIR/topology.txt"
lscpu > "$OUT_DIR/cpu.txt"
scontrol show job "$SLURM_JOB_ID" > "$OUT_DIR/allocation.txt"

setsid "$AEGIS_PYTHON" -u "$TASK_DIR/launch_prefill_sparse.py" \
  --model "$AEGIS_MODEL" --output "$OUT_DIR" \
  --contexts "${AEGIS_CONTEXTS:-8192,65536,262144,1010000}" --reuse-repeats 3 \
  --full-repeats "${AEGIS_FULL_REPEATS:-1}" --full-warmups "${AEGIS_FULL_WARMUPS:-0}" \
  --sparse-head-group "${AEGIS_SPARSE_HEAD_GROUP:-2}" "${AEGIS_STORAGE_ARGS[@]}" &
AEGIS_WORKER_PID=$!
wait "$AEGIS_WORKER_PID"
