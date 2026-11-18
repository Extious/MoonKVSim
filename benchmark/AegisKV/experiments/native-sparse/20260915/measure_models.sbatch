#!/bin/bash
#SBATCH --job-name=native-four-models
#SBATCH --partition=long
#SBATCH --nodelist=gpu16
#SBATCH --gres=gpu:rtx4090:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=02:00:00
#SBATCH --output=/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260915/four-models-%j.log
# All four models run sequentially on the SAME allocated GPU, with retained KV.
# Override partition/gres/nodelist at submission only for a known available GPU.
# No result is added to Figure 1 until all required inputs pass the measurement audit.
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
# The CPU-only preparation dependency must succeed first. Recheck offline;
# never download or wait for checkpoints while holding a GPU allocation.
"$PY" -u benchmark/AegisKV/experiments/native-sparse/20260915/prepare_measure_models.py --verify-only
printf 'MEASUREMENT_JOB=%s NODE=%s CUDA_VISIBLE_DEVICES=%s\n' \
  "$SLURM_JOB_ID" "$(hostname)" "${CUDA_VISIBLE_DEVICES:-unset}"
nvidia-smi
TAG="retained-kv-${SLURM_JOB_ID}"
for MODEL in nosa-1b minicpm4-8b nosa-3b nosa-8b; do
  "$PY" -u benchmark/AegisKV/experiments/native-sparse/20260915/measure_prefill.py --model "$MODEL" \
    --contexts 8192 16384 32768 65536 98304 131072 --repeats 5 --out-tag "$TAG"
done
printf 'FOUR_MODELS_DONE tag=%s\n' "$TAG"
