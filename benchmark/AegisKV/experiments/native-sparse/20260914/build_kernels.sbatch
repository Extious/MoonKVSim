#!/bin/bash
#SBATCH --job-name=nosa-native-build
#SBATCH --partition=debug
#SBATCH --nodelist=gpu10
#SBATCH --gres=gpu:rtx4090:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --output=/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260914/build-%j.log
set -euo pipefail
TASK_ROOT=/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/runtime-20260914
TASK_PY="$TASK_ROOT/venv/bin/python"
export PATH="$TASK_ROOT/venv/bin:/usr/local/cuda-12.8/bin:$PATH"
export CUDA_HOME=/usr/local/cuda-12.8
export CPATH="$TASK_ROOT/venv/lib/python3.12/site-packages/nvidia/cuda_cccl/include:/home/comp/zhanzhao/sglang/.venv/lib/python3.12/site-packages/nvidia/cuda_runtime/include:/usr/local/cuda-12.8/include:${CPATH:-}"
export LIBRARY_PATH="$TASK_ROOT/cuda-lib:${LIBRARY_PATH:-}"
export MAX_JOBS=2
export TORCH_EXTENSIONS_DIR="$TASK_ROOT/torch-extensions"
export TRITON_CACHE_DIR="$TASK_ROOT/triton-cache"
cd "$TASK_ROOT/upstream/source/NOSA-1cbee77d607f9051b206a09c862bea28becb9e67/dependencies/infllmv2_cuda_impl"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
"$TASK_PY" setup.py build_ext --inplace
"$TASK_PY" -c 'import torch, infllm_v2; print("NATIVE_KERNEL_READY", torch.__version__, infllm_v2.__file__)'
