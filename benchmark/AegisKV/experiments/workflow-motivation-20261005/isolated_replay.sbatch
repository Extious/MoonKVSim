#!/bin/bash
#SBATCH --job-name=aegis-real-trace-isolated-agent-loss
#SBATCH --partition=short
#SBATCH --nodelist=gpu20
#SBATCH --gres=gpu:l40s:2
#SBATCH --cpus-per-task=12
#SBATCH --mem=120G
#SBATCH --time=01:00:00
#SBATCH --output=/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/isolated-%j.log
set -euo pipefail
cd /home/comp/zhanzhao/MoonKVSim
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4
export PYTORCH_ALLOC_CONF=expandable_segments:True
benchmark/AegisKV/experiments/native-sparse/runtime-20260914/venv/bin/python -u benchmark/AegisKV/experiments/workflow-motivation-20261005/isolated_replay.py
