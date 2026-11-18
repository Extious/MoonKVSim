#!/bin/bash
#SBATCH --job-name=aegis-qwen1m-reuse
#SBATCH --partition=short
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:4
#SBATCH --constraint=a100|h20
#SBATCH --mem=220G
#SBATCH --time=12:00:00
#SBATCH --output=logs/%x-%j.log
set -euo pipefail
TASK_DIR=/home/comp/25482351/aegiskv_reuse_qwen25_1m_20260919
cd "$TASK_DIR"
source "$TASK_DIR/job_environment.sh"
test -f MODEL_COMPLETE
OUT_DIR="$TASK_DIR/results/${SLURM_JOB_ID}"
mkdir -p "$OUT_DIR"
nvidia-smi -q > "$OUT_DIR/nvidia-smi-before.txt"
nvidia-smi topo -m > "$OUT_DIR/topology.txt"
lscpu > "$OUT_DIR/cpu.txt"
scontrol show job "$SLURM_JOB_ID" > "$OUT_DIR/allocation.txt"
export OMP_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 NCCL_DEBUG=WARN
export TP="${TP:-4}"
export PYTHONPATH="/home/comp/25482351/sglang/python:${PYTHONPATH:-}"
/home/comp/25482351/sglang/.venv/bin/python -u "$TASK_DIR/preflight.py"
/home/comp/25482351/sglang/.venv/bin/python "$TASK_DIR/launch_sglang.py" \
  --model /home/comp/25482351/.cache/huggingface/hub/models--Qwen--Qwen2.5-7B-Instruct-1M/snapshots/e28526f7bb80e2a9c8af03b831a9af3812f18fba \
  --output "$OUT_DIR" \
  --contexts "${CONTEXTS:-8192,16384,32768,65536,131072,262144,524288,786432,1010000}" \
  --inputs "${INPUTS:-5}" --repeats "${REPEATS:-5}" --warmup "${WARMUP:-1}"
python3 "$TASK_DIR/aggregate.py" "$OUT_DIR"
nvidia-smi -q > "$OUT_DIR/nvidia-smi-after.txt"
