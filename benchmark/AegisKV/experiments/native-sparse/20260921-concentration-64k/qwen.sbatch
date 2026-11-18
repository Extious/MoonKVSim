#!/bin/bash
#SBATCH --job-name=kv64-qwen
#SBATCH --partition=short
#SBATCH --nodelist=gpu28
#SBATCH --gres=gpu:a100:2
#SBATCH --cpus-per-task=8
#SBATCH --mem=80G
#SBATCH --time=00:30:00
#SBATCH --output=/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260921-concentration-64k/qwen-%j.log
set -euo pipefail
cd /home/comp/zhanzhao/MoonKVSim
TASK_RUNTIME="$PWD/benchmark/AegisKV/experiments/native-sparse/runtime-20260914"
export PATH="$TASK_RUNTIME/venv/bin:/usr/local/cuda-12.8/bin:$PATH"
export CUDA_HOME=/usr/local/cuda-12.8
export HF_HOME="$TASK_RUNTIME/hf-runtime-cache"
export TRITON_CACHE_DIR="$PWD/benchmark/AegisKV/experiments/native-sparse/runtime-20260921/triton-cache"
export TORCH_EXTENSIONS_DIR="$TASK_RUNTIME/torch-extensions"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PYTORCH_ALLOC_CONF=expandable_segments:True
"$TASK_RUNTIME/venv/bin/python" -u /home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260921-concentration-64k/capture_qwen.py
