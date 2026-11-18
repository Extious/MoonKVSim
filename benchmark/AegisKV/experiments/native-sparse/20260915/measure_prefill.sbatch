#!/bin/bash
#SBATCH --job-name=native-prefill-latency
#SBATCH --partition=long
#SBATCH --nodelist=gpu18
#SBATCH --gres=gpu:rtx4090:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=03:00:00
#SBATCH --output=/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260915/measure-%j.log
set -euo pipefail
TASK_ROOT=/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/runtime-20260914
export PATH="$TASK_ROOT/venv/bin:/usr/local/cuda-12.8/bin:$PATH"
export CUDA_HOME=/usr/local/cuda-12.8
export HF_HOME="$TASK_ROOT/hf-runtime-cache"
export TRITON_CACHE_DIR="$TASK_ROOT/triton-cache"
export TORCH_EXTENSIONS_DIR="$TASK_ROOT/torch-extensions"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PYTORCH_ALLOC_CONF=expandable_segments:True
cd /home/comp/zhanzhao/MoonKVSim
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
PY="$TASK_ROOT/venv/bin/python"
"$PY" -u benchmark/AegisKV/experiments/native-sparse/20260915/measure_prefill.py --model minicpm4-8b --contexts 8192 16384 32768
"$PY" -u benchmark/AegisKV/experiments/native-sparse/20260915/measure_prefill.py --model nosa-1b --contexts 8192 16384 32768 65536 131072
echo JOB_DONE
