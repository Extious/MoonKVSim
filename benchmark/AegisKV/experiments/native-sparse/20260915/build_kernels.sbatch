#!/bin/bash
#SBATCH --job-name=infllmv2-upstream-build
#SBATCH --partition=long
#SBATCH --nodelist=gpu18
#SBATCH --gres=gpu:rtx4090:1
#SBATCH --cpus-per-task=24
#SBATCH --mem=96G
#SBATCH --time=02:00:00
#SBATCH --output=/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260915/build-%j.log
set -euo pipefail
NOSA_ROOT=/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/runtime-20260914
TASK_ROOT=/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/runtime-20260915
TASK_PY="$NOSA_ROOT/venv/bin/python"
export PATH="$NOSA_ROOT/venv/bin:/usr/local/cuda-12.8/bin:$PATH"
export CUDA_HOME=/usr/local/cuda-12.8
export CPATH="$NOSA_ROOT/venv/lib/python3.12/site-packages/nvidia/cuda_cccl/include:/home/comp/zhanzhao/sglang/.venv/lib/python3.12/site-packages/nvidia/cuda_runtime/include:/usr/local/cuda-12.8/include:${CPATH:-}"
export LIBRARY_PATH="$NOSA_ROOT/cuda-lib:${LIBRARY_PATH:-}"
export MAX_JOBS=20
export INFLLM_ARCHS="80"
export TORCH_EXTENSIONS_DIR="$TASK_ROOT/torch-extensions"
export TRITON_CACHE_DIR="$NOSA_ROOT/triton-cache"
cd "$TASK_ROOT/infllmv2_cuda_impl"
git log -1 --format="upstream infllmv2_cuda_impl %H %cd"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
"$TASK_PY" setup.py build_ext --inplace
"$TASK_PY" -c 'import torch, sys; sys.path.insert(0, "."); import infllm_v2, inspect; print("UPSTREAM_KERNEL_READY", torch.__version__, infllm_v2.__file__); print(inspect.signature(infllm_v2.infllmv2_attn_stage1))'
