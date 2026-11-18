#!/bin/bash
#SBATCH --job-name=aegis-qwen1m-env
#SBATCH --partition=short
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --constraint=a100|h20
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=00:15:00
#SBATCH --output=logs/env-%j.log
set -euo pipefail
TASK_DIR=/home/comp/25482351/aegiskv_reuse_qwen25_1m_20260919
cd "$TASK_DIR"
source "$TASK_DIR/job_environment.sh"
date -Iseconds
hostname
export PYTHONPATH=/home/comp/25482351/sglang/python
export TP=1 OMP_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false
/home/comp/25482351/sglang/.venv/bin/python -u "$TASK_DIR/preflight.py"
