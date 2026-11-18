#!/bin/bash
#SBATCH --job-name=minicpm4-a100-prefill
#SBATCH --partition=short
#SBATCH --gres=gpu:a100:2
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=02:00:00
#SBATCH --output=/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260915/a100-minicpm4-%j.log
# Figure 1 (2026-09-17 design): MiniCPM4-8B is the only measured curve; the Qwen3-8B / Qwen3-30B-A3B
# reference curves come from AIConfigurator A100 estimates (experiments/data/recompute-aiconfigurator-a100).
# Protocol v2 (measure_prefill.py): BF16, batch 1, retained KV, 5 timed repeats per shape, 8K-128K.
# The same allocation then measures the unsealed-tail replay cost (measure_replay.py) so that the design
# constants (Sec. 3) can be quoted on the same GPU as Figure 1.
# Both A100s of the node are requested although one is used: on this cluster a co-scheduled job can land its
# process on our card (job 152548 was refused for exactly that reason), so no other Slurm job may share the node.
# The scripts still refuse to measure if a foreign compute process holds the selected GPU.
set -euo pipefail
cd /home/comp/zhanzhao/MoonKVSim
TASK_ROOT="$PWD/benchmark/AegisKV/experiments/native-sparse/runtime-20260914"
export PATH="$TASK_ROOT/venv/bin:/usr/local/cuda-12.8/bin:$PATH"
export CUDA_HOME=/usr/local/cuda-12.8
export HF_HOME="$TASK_ROOT/hf-runtime-cache"
export TRITON_CACHE_DIR="$TASK_ROOT/triton-cache"
export TORCH_EXTENSIONS_DIR="$TASK_ROOT/torch-extensions"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PYTORCH_ALLOC_CONF=expandable_segments:True
PY="$TASK_ROOT/venv/bin/python"
printf 'MEASUREMENT_JOB=%s NODE=%s CUDA_VISIBLE_DEVICES=%s\n' \
  "$SLURM_JOB_ID" "$(hostname)" "${CUDA_VISIBLE_DEVICES:-unset}"
nvidia-smi --query-gpu=index,uuid,name,memory.total,memory.used,driver_version,pcie.link.gen.current --format=csv
nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory --format=csv

# Pick the first allocated GPU without a foreign compute process; wait up to 15 minutes for one to free up.
pick_gpu() {
  local busy idx uuid
  busy="$(nvidia-smi --query-compute-apps=gpu_uuid --format=csv,noheader | tr -d ' ')"
  for idx in ${CUDA_VISIBLE_DEVICES//,/ }; do
    uuid="$(nvidia-smi --query-gpu=uuid --format=csv,noheader -i "$idx" | tr -d ' ')"
    if ! grep -qx "$uuid" <<<"$busy"; then echo "$idx"; return 0; fi
  done
  return 1
}
for attempt in $(seq 1 30); do
  if GPU="$(pick_gpu)"; then break; fi
  echo "attempt $attempt: every allocated GPU has a foreign compute process; waiting 30 s"; sleep 30; GPU=""
done
[ -n "${GPU:-}" ] || { echo NO_CLEAN_GPU; exit 2; }
export CUDA_VISIBLE_DEVICES="$GPU"
echo "SELECTED_GPU=$GPU"

TAG="a100-${SLURM_JOB_ID}"
"$PY" -u benchmark/AegisKV/experiments/native-sparse/20260915/measure_prefill.py --model minicpm4-8b \
  --contexts 8192 16384 32768 65536 98304 131072 --repeats 5 --out-tag "$TAG"
printf 'MINICPM4_A100_PREFILL_DONE tag=%s\n' "$TAG"
"$PY" -u benchmark/AegisKV/experiments/native-sparse/20260915/measure_replay.py \
  --contexts 8192 16384 32768 65536 98304 131072 --tails 1 64 512 --repeats 5 --out-tag "$TAG" \
  || echo MINICPM4_A100_REPLAY_FAILED
printf 'MINICPM4_A100_DONE tag=%s\n' "$TAG"
