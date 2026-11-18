#!/bin/bash
#SBATCH --job-name=aegis-reuse-probe
#SBATCH --partition=long
#SBATCH --gres=gpu:rtx4090:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=00:20:00
#SBATCH --output=/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260918-reuse/probe-%j.log
set -euo pipefail
cd /home/comp/zhanzhao/MoonKVSim
TASK_RUNTIME="$PWD/benchmark/AegisKV/experiments/native-sparse/runtime-20260914"
export PATH="$TASK_RUNTIME/venv/bin:/usr/local/cuda-12.8/bin:$PATH"
export CUDA_HOME=/usr/local/cuda-12.8
export HF_HOME="$TASK_RUNTIME/hf-runtime-cache"
export TRITON_CACHE_DIR="$TASK_RUNTIME/triton-cache"
export TORCH_EXTENSIONS_DIR="$TASK_RUNTIME/torch-extensions"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PYTHONBREAKPOINT=0
export PYTORCH_ALLOC_CONF=expandable_segments:True
for MODEL in minicpm4-8b nosa-1b nosa-3b; do
  "$TASK_RUNTIME/venv/bin/python" -u benchmark/AegisKV/experiments/native-sparse/20260918-reuse/probe_cached_tail.py --model "$MODEL" --out "benchmark/AegisKV/experiments/native-sparse/20260918-reuse/probe-${MODEL}-${SLURM_JOB_ID}.json"
done
