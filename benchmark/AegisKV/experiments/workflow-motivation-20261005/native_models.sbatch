#!/bin/bash
#SBATCH --job-name=aegis-new-three-models
#SBATCH --partition=long
#SBATCH --nodelist=gpu12
#SBATCH --gres=gpu:rtx4090:2
#SBATCH --cpus-per-task=8
#SBATCH --mem=80G
#SBATCH --time=00:30:00
#SBATCH --output=/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/native-models-%j.log
set -euo pipefail
cd /home/comp/zhanzhao/MoonKVSim
TASK_RUNTIME="$PWD/benchmark/AegisKV/experiments/native-sparse/runtime-20260914"
export PATH="$TASK_RUNTIME/venv/bin:/usr/local/cuda-12.8/bin:$PATH"
export CUDA_HOME=/usr/local/cuda-12.8
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export HF_HOME="$TASK_RUNTIME/hf-runtime-cache"
export TRITON_CACHE_DIR="$PWD/benchmark/AegisKV/experiments/workflow-motivation-20261005/triton-cache"
export TORCH_EXTENSIONS_DIR="$TASK_RUNTIME/torch-extensions"
export PYTORCH_ALLOC_CONF=expandable_segments:True
"$TASK_RUNTIME/venv/bin/python" -u benchmark/AegisKV/experiments/workflow-motivation-20261005/native_models.py --model NOSA-8B
"$TASK_RUNTIME/venv/bin/python" -u benchmark/AegisKV/experiments/workflow-motivation-20261005/native_models.py --model NSA-8B
"$TASK_RUNTIME/venv/bin/python" -u benchmark/AegisKV/experiments/workflow-motivation-20261005/native_models.py --model MiniCPM4.1-8B
