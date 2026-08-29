#!/usr/bin/env bash
#SBATCH --job-name=moonkvsim-qwen128k
#SBATCH --partition=short
#SBATCH --constraint=l40s
#SBATCH --gres=gpu:l40s:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=benchmark/physical/qwen3-8b-context/slurm-%j.wrapper.out
#SBATCH --error=benchmark/physical/qwen3-8b-context/slurm-%j.wrapper.err

set -uo pipefail

expected_repo_root="/home/comp/zhanzhao/MoonKVSim"
submitted_root="${SLURM_SUBMIT_DIR:-}"
if [[ -z "${submitted_root}" || ! -d "${submitted_root}" ]]; then
  echo "MOONKVSIM_PROBE_ERROR=missing_slurm_submit_dir" >&2
  exit 63
fi
repo_root="$(cd -- "${submitted_root}" && pwd -P)"
if [[ "${repo_root}" != "${expected_repo_root}" ]]; then
  echo "MOONKVSIM_PROBE_ERROR=unexpected_submit_dir:${repo_root}" >&2
  exit 63
fi
runtime_python="/home/comp/zhanzhao/Mooncake/aegiskv/.venv-vllm-sm89/bin/python"
probe_script="${repo_root}/scripts/physical/qwen3_8b_vllm_context_probe.py"
source_lock="${repo_root}/reference/source-lock.json"
artifact_root="${repo_root}/benchmark/physical/qwen3-8b-context"
job_id="${SLURM_JOB_ID:-}"

if [[ -z "${job_id}" || ! "${job_id}" =~ ^[0-9]+$ ]]; then
  echo "MOONKVSIM_PROBE_ERROR=missing_numeric_slurm_job_id" >&2
  exit 64
fi
if [[ ! -x "${runtime_python}" ]]; then
  echo "MOONKVSIM_PROBE_ERROR=missing_runtime_python:${runtime_python}" >&2
  exit 65
fi
if [[ ! -f "${probe_script}" || ! -f "${source_lock}" ]]; then
  echo "MOONKVSIM_PROBE_ERROR=missing_probe_input" >&2
  exit 66
fi

mkdir -p -- "${artifact_root}"
final_dir="${artifact_root}/${job_id}"
if [[ -e "${final_dir}" || -L "${final_dir}" ]]; then
  echo "MOONKVSIM_PROBE_ERROR=refusing_existing_run:${final_dir}" >&2
  exit 73
fi
staging_dir="$(mktemp -d "${artifact_root}/.${job_id}.staging.XXXXXX")"
probe_snapshot="${staging_dir}/qwen3_8b_vllm_context_probe.py"
cp -- "${probe_script}" "${probe_snapshot}"
chmod 0755 -- "${probe_snapshot}"
export MOONKVSIM_PROBE_SCRIPT_SHA256
MOONKVSIM_PROBE_SCRIPT_SHA256="$(sha256sum -- "${probe_snapshot}" | awk '{print $1}')"

batch_capture_stdout="${staging_dir}/batch-script-capture.stdout.log"
batch_capture_stderr="${staging_dir}/batch-script-capture.stderr.log"
submitted_batch_script="${staging_dir}/submitted-batch-script.sh"
if scontrol write batch_script "${job_id}" "${submitted_batch_script}" \
  > "${batch_capture_stdout}" 2> "${batch_capture_stderr}" \
  && [[ -s "${submitted_batch_script}" ]]; then
  export MOONKVSIM_BATCH_SCRIPT_CAPTURE_STATUS=PASS
  export MOONKVSIM_SUBMITTED_BATCH_SCRIPT_SHA256
  MOONKVSIM_SUBMITTED_BATCH_SCRIPT_SHA256="$(
    sha256sum -- "${submitted_batch_script}" | awk '{print $1}'
  )"
else
  export MOONKVSIM_BATCH_SCRIPT_CAPTURE_STATUS=FAIL
  export MOONKVSIM_SUBMITTED_BATCH_SCRIPT_SHA256=""
  printf '%s\n' \
    "Slurm-spooled batch script capture failed; physical probe must fail closed." \
    > "${staging_dir}/BATCH_SCRIPT_CAPTURE_FAILED.txt"
fi

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PYTHONHASHSEED=0
export VLLM_USE_V1=1

{
  echo "schema=moonkvsim.qwen3_8b_context_runtime.v1"
  echo "observed_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "hostname=$(hostname)"
  echo "slurm_job_id=${job_id}"
  echo "slurm_job_partition=${SLURM_JOB_PARTITION:-}"
  echo "slurm_job_gpus=${SLURM_JOB_GPUS:-}"
  echo "slurm_cuda_visible_devices=${CUDA_VISIBLE_DEVICES:-}"
  echo "slurm_node=${SLURMD_NODENAME:-}"
  echo "slurm_cpus_per_task=${SLURM_CPUS_PER_TASK:-}"
  echo "slurm_mem_per_node=${SLURM_MEM_PER_NODE:-}"
  echo "runtime_python=${runtime_python}"
  echo "probe_script=${probe_script}"
  echo "executed_probe_snapshot=${probe_snapshot}"
  echo "executed_probe_snapshot_sha256=${MOONKVSIM_PROBE_SCRIPT_SHA256}"
  echo "batch_script_capture_status=${MOONKVSIM_BATCH_SCRIPT_CAPTURE_STATUS}"
  echo "submitted_batch_script_sha256=${MOONKVSIM_SUBMITTED_BATCH_SCRIPT_SHA256}"
  echo "source_lock=${source_lock}"
  echo "hf_hub_offline=${HF_HUB_OFFLINE}"
  echo "transformers_offline=${TRANSFORMERS_OFFLINE}"
  echo "hf_datasets_offline=${HF_DATASETS_OFFLINE}"
} > "${staging_dir}/runtime.txt"

{
  echo "# scontrol show job -dd -o ${job_id}"
  scontrol show job -dd -o "${job_id}" 2>&1 || true
  echo "# sacct -X -j ${job_id}"
  sacct -X -j "${job_id}" \
    --format=JobIDRaw,JobName,Partition,State,AllocTRES,NodeList,Start,Elapsed,Timelimit \
    --parsable2 2>&1 || true
} > "${staging_dir}/slurm-job.txt"

"${runtime_python}" "${probe_snapshot}" \
  --source-lock "${source_lock}" \
  --artifact-dir "${staging_dir}" \
  --output "${staging_dir}/result.json" \
  --worker-timeout-seconds 5400 \
  > "${staging_dir}/stdout.log" \
  2> "${staging_dir}/stderr.log"
probe_status=$?
printf '%s\n' "${probe_status}" > "${staging_dir}/probe-exit-code.txt"

{
  echo "# scontrol show job -dd -o ${job_id} (post-probe)"
  scontrol show job -dd -o "${job_id}" 2>&1 || true
  echo "# sstat -j ${job_id}.batch (post-probe)"
  sstat -j "${job_id}.batch" \
    --format=JobID,AveCPU,MaxRSS,MaxVMSize,AveRSS \
    --parsable2 2>&1 || true
} >> "${staging_dir}/slurm-job.txt"

if [[ ! -s "${staging_dir}/result.json" ]]; then
  printf '%s\n' \
    "probe process did not produce result.json; see stderr.log and probe-exit-code.txt" \
    > "${staging_dir}/WRAPPER_FAILURE.txt"
  if [[ "${probe_status}" -eq 0 ]]; then
    probe_status=74
  fi
fi

(
  cd -- "${staging_dir}" || exit 1
  while IFS= read -r -d '' artifact; do
    sha256sum -- "${artifact}"
  done < <(
    find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 | sort -z
  )
) > "${staging_dir}/SHA256SUMS"
checksum_status=$?
if [[ "${checksum_status}" -ne 0 ]]; then
  echo "MOONKVSIM_PROBE_ERROR=checksum_generation_failed:${staging_dir}" >&2
  exit 75
fi

"${runtime_python}" "${probe_snapshot}" \
  --publish-staging "${staging_dir}" \
  --publish-final "${final_dir}"
publish_status=$?
if [[ "${publish_status}" -ne 0 ]]; then
  echo "MOONKVSIM_PROBE_ERROR=publication_failed:${staging_dir}" >&2
  exit 76
fi

exit "${probe_status}"
