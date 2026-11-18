#!/bin/bash
#SBATCH --job-name=insight-seer8b
#SBATCH --partition=long
#SBATCH --gres=gpu:rtx4090:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=00:35:00
#SBATCH --output=/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260918-seer/capture-%j.log
set -euo pipefail
cd /home/comp/zhanzhao/MoonKVSim
TASK_ROOT="$PWD/benchmark/AegisKV/experiments/native-sparse/runtime-20260914"
export PATH="$TASK_ROOT/venv/bin:/usr/local/cuda-12.8/bin:$PATH"
export CUDA_HOME=/usr/local/cuda-12.8
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export TRITON_CACHE_DIR="$PWD/benchmark/AegisKV/experiments/native-sparse/20260918-seer/triton-cache"
export PYTORCH_ALLOC_CONF=expandable_segments:True
"$TASK_ROOT/venv/bin/python" -u benchmark/AegisKV/experiments/native-sparse/20260918-seer/capture_seer.py
