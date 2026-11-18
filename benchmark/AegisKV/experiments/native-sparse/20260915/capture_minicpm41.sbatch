#!/bin/bash
#SBATCH --job-name=figure4-minicpm41
#SBATCH --partition=long
#SBATCH --nodelist=gpu16
#SBATCH --gres=gpu:rtx4090:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=00:45:00
#SBATCH --output=/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260915/figure4-minicpm41-%j.log
# Requires successful CPU-only MiniCPM4.1 preparation; wait until the existing
# Figure 1 and NOSA-3B jobs finish. Do not change or download official kernels.
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
printf 'CAPTURE_JOB=%s NODE=%s CUDA_VISIBLE_DEVICES=%s\n' \
  "$SLURM_JOB_ID" "$(hostname)" "${CUDA_VISIBLE_DEVICES:-unset}"
"$TASK_ROOT/venv/bin/python" -u benchmark/AegisKV/experiments/native-sparse/20260915/capture_minicpm4.py \
  --model MiniCPM4.1-8B --histories 32768 --suffix 512 --books 10146 10321 10356
EXTRAS=(--extra-model MiniCPM4.1-8B)
NOSA="$PWD/benchmark/AegisKV/experiments/native-sparse/20260915-nosa-3b"
if [[ -f "$NOSA/traces/pg19-10146-M32768-N512/run.json" && \
      -f "$NOSA/traces/pg19-10321-M32768-N512/run.json" && \
      -f "$NOSA/traces/pg19-10356-M32768-N512/run.json" ]]; then
  EXTRAS+=(--extra-model NOSA-3B)
else
  printf 'NOSA3B_NOT_INCLUDED: incomplete capture; no missing model is synthesized\n'
fi
# Analysis verifies provenance, observer outputs and every source-layer hash.
TABLES="$PWD/benchmark/AegisKV/experiments/native-sparse/20260915/figure4-candidate-${SLURM_JOB_ID}"
FIGURES="$PWD/benchmark/AegisKV/paper/figures/candidates/figure4-${SLURM_JOB_ID}"
.venv/bin/python benchmark/AegisKV/experiments/native-sparse/20260915/analyze_models.py "${EXTRAS[@]}" --out-dir "$TABLES"
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_draft_20260915.py \
  --only motivation-sparse --sparse-data-dir "$TABLES" --out-dir "$FIGURES"
printf 'FIGURE4_CANDIDATE_READY tables=%s figures=%s\n' "$TABLES" "$FIGURES"
