#!/bin/bash
#SBATCH --job-name=figure4-nosa3b
#SBATCH --partition=long
#SBATCH --nodelist=gpu16
#SBATCH --gres=gpu:rtx4090:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=00:45:00
#SBATCH --output=/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260915/figure4-capture-%j.log
# Submit after the existing CPU-only checkpoint preparation succeeds and the
# Figure 1 GPU campaign ends. No downloads or paper publication in this job.
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
printf 'CAPTURE_JOB=%s NODE=%s CUDA_VISIBLE_DEVICES=%s\n' \
  "$SLURM_JOB_ID" "$(hostname)" "${CUDA_VISIBLE_DEVICES:-unset}"
"$PY" -u benchmark/AegisKV/experiments/native-sparse/20260914/capture_native.py \
  --model NOSA-3B --histories 32768 --suffix 512 --books 10146 10321 10356
# Stage all cross-model tables and the candidate figure separately. Existing
# figures/captions stay unchanged until numerical and visual review is complete.
TABLES="$PWD/benchmark/AegisKV/experiments/native-sparse/20260915/figure4-candidate-${SLURM_JOB_ID}"
FIGURES="$PWD/benchmark/AegisKV/paper/figures/candidates/figure4-${SLURM_JOB_ID}"
.venv/bin/python benchmark/AegisKV/experiments/native-sparse/20260915/analyze_models.py \
  --extra-model NOSA-3B --out-dir "$TABLES"
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_draft_20260915.py \
  --only motivation-sparse --sparse-data-dir "$TABLES" --out-dir "$FIGURES"
printf 'FIGURE4_CANDIDATE_READY tables=%s figures=%s\n' "$TABLES" "$FIGURES"
