#!/usr/bin/env bash
#SBATCH --job-name=moonkv-aic-l40s-tp1
#SBATCH --partition=short
#SBATCH --constraint=l40s
#SBATCH --gres=gpu:l40s:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=04:00:00
#SBATCH --output=benchmark/physical/aiconfigurator-vllm-forward/slurm-%j.wrapper.out
#SBATCH --error=benchmark/physical/aiconfigurator-vllm-forward/slurm-%j.wrapper.err

set -Eeuo pipefail

expected_repo_root="/home/comp/zhanzhao/MoonKVSim"
submit_dir="${SLURM_SUBMIT_DIR:-}"
if [[ "${submit_dir}" != "${expected_repo_root}" || ! -d "${submit_dir}" ]]; then
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=unexpected_slurm_submit_dir:${submit_dir}" >&2
  exit 3
fi
repo_root="$(cd -- "${submit_dir}" && pwd -P)"
if [[ "${repo_root}" != "${expected_repo_root}" ]]; then
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=resolved_submit_dir_drift:${repo_root}" >&2
  exit 3
fi
runtime_python="/home/comp/zhanzhao/Mooncake/aegiskv/.venv-vllm-sm89/bin/python"
repository_harness="${repo_root}/scripts/physical/qwen3_8b_vllm_forward_calibration.py"
repository_plan="${repo_root}/configs/physical/aiconfigurator/qwen3-8b-l40s-native-40960/shape-plan.json"
repository_thresholds="${repo_root}/configs/physical/aiconfigurator/qwen3-8b-l40s-native-40960/residual-thresholds.json"
repository_source_lock="${repo_root}/reference/source-lock.json"
repository_support_audit="${repo_root}/reference/aiconfigurator-support.json"
artifact_root="${repo_root}/benchmark/physical/aiconfigurator-vllm-forward"

hardware_profile=""
tp_size=""
pp_size=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --hardware-profile)
      if [[ $# -lt 2 ]]; then
        echo "MOONKVSIM_AIC_WRAPPER_ERROR=missing_value:$1" >&2
        exit 2
      fi
      hardware_profile="${2:-}"
      shift 2
      ;;
    --tp-size)
      if [[ $# -lt 2 ]]; then
        echo "MOONKVSIM_AIC_WRAPPER_ERROR=missing_value:$1" >&2
        exit 2
      fi
      tp_size="${2:-}"
      shift 2
      ;;
    --pp-size)
      if [[ $# -lt 2 ]]; then
        echo "MOONKVSIM_AIC_WRAPPER_ERROR=missing_value:$1" >&2
        exit 2
      fi
      pp_size="${2:-}"
      shift 2
      ;;
    *)
      echo "MOONKVSIM_AIC_WRAPPER_ERROR=unknown_argument:$1" >&2
      exit 2
      ;;
  esac
done
if [[ "${hardware_profile}" != "l40s" || "${tp_size}" != "1" || "${pp_size}" != "1" ]]; then
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=only_l40s_tp1_pp1_is_implemented" >&2
  exit 2
fi

job_id="${SLURM_JOB_ID:-}"
if [[ -z "${job_id}" || ! "${job_id}" =~ ^[0-9]+$ ]]; then
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=missing_numeric_slurm_job_id" >&2
  exit 4
fi
if [[ "${SLURM_JOB_PARTITION:-}" != "short" ]]; then
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=allocation_not_in_short" >&2
  exit 4
fi
IFS=',' read -r -a visible_devices <<< "${CUDA_VISIBLE_DEVICES:-}"
if [[ ${#visible_devices[@]} -ne 1 || -z "${visible_devices[0]}" ]]; then
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=exactly_one_visible_gpu_required" >&2
  exit 4
fi
if [[ ! -x "${runtime_python}" ]]; then
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=missing_pinned_runtime:${runtime_python}" >&2
  exit 3
fi
for required in \
  "${repository_harness}" \
  "${repository_plan}" \
  "${repository_thresholds}" \
  "${repository_source_lock}" \
  "${repository_support_audit}"; do
  if [[ ! -f "${required}" || -L "${required}" ]]; then
    echo "MOONKVSIM_AIC_WRAPPER_ERROR=missing_or_unsafe_input:${required}" >&2
    exit 3
  fi
done

if ! mkdir -p -- "${artifact_root}"; then
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=artifact_root_creation_failed:${artifact_root}" >&2
  exit 8
fi
final_dir="${artifact_root}/${job_id}"
if [[ -e "${final_dir}" || -L "${final_dir}" ]]; then
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=refusing_existing_output:${final_dir}" >&2
  exit 8
fi
if ! staging_dir="$(mktemp -d "/tmp/moonkvsim-aic-${job_id}.XXXXXX")"; then
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=staging_creation_failed" >&2
  exit 8
fi
case "${staging_dir}" in
  "/tmp/moonkvsim-aic-${job_id}."??????) ;;
  *)
    echo "MOONKVSIM_AIC_WRAPPER_ERROR=unsafe_mktemp_result:${staging_dir}" >&2
    exit 8
    ;;
esac

staged_harness="${staging_dir}/qwen3_8b_vllm_forward_calibration.py"
if ! cp -- "${repository_harness}" "${staged_harness}" \
  || ! cp -- "${repository_plan}" "${staging_dir}/shape-plan.json" \
  || ! cp -- "${repository_thresholds}" "${staging_dir}/residual-thresholds.json" \
  || ! cp -- "${repository_source_lock}" "${staging_dir}/source-lock.json" \
  || ! cp -- "${repository_support_audit}" "${staging_dir}/aiconfigurator-support.json" \
  || ! chmod 0755 -- "${staged_harness}"; then
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=input_staging_failed" >&2
  echo "MOONKVSIM_AIC_STAGING_PRESERVED=${staging_dir}" >&2
  exit 3
fi

slurm_job_capture="${staging_dir}/slurm-job.txt"
slurm_partition_capture="${staging_dir}/slurm-partition-short.txt"
if ! scontrol show job -dd -o "${job_id}" > "${slurm_job_capture}" 2>&1 \
  || ! grep -Eq '(^|[[:space:]])JobState=RUNNING([[:space:]]|$)' "${slurm_job_capture}" \
  || ! grep -Eq '(^|[[:space:]])Partition=short([[:space:]]|$)' "${slurm_job_capture}" \
  || ! grep -Eq '(^|[[:space:]])Features=l40s([[:space:]]|$)' "${slurm_job_capture}" \
  || ! grep -Eq '(^|[[:space:]])TresPerNode=gpu:l40s:1([[:space:]]|$)' \
    "${slurm_job_capture}" \
  || ! grep -Eq '(^|[[:space:]])TRES=[^[:space:]]*gres/gpu=1([,[:space:]]|$)' \
    "${slurm_job_capture}" \
  || ! grep -Eq '(^|[[:space:]])TRES=[^[:space:]]*gres/gpu:l40s=1([,[:space:]]|$)' \
    "${slurm_job_capture}"; then
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=assigned_l40s_gres_binding_not_verified" >&2
  echo "MOONKVSIM_AIC_STAGING_PRESERVED=${staging_dir}" >&2
  exit 4
fi
if ! scontrol show partition short -o > "${slurm_partition_capture}" 2>&1 \
  || ! grep -Eq '(^|[[:space:]])PartitionName=short([[:space:]]|$)' \
    "${slurm_partition_capture}" \
  || ! grep -Eq '(^|[[:space:]])OverSubscribe=FORCE:4([[:space:]]|$)' \
    "${slurm_partition_capture}"; then
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=short_partition_share_policy_not_verified" >&2
  echo "MOONKVSIM_AIC_STAGING_PRESERVED=${staging_dir}" >&2
  exit 4
fi
if ! job_oversubscribe="$(
  grep -oE '(^|[[:space:]])OverSubscribe=[^[:space:]]+' "${slurm_job_capture}" \
    | head -n 1 | cut -d= -f2
)" || [[ -z "${job_oversubscribe}" ]]; then
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=job_oversubscribe_field_not_recorded" >&2
  echo "MOONKVSIM_AIC_STAGING_PRESERVED=${staging_dir}" >&2
  exit 4
fi
export MOONKVSIM_ASSIGNED_GPU_ALLOCATION=PASS
export MOONKVSIM_SLURM_JOB_OVERSUBSCRIBE="${job_oversubscribe}"
export MOONKVSIM_SLURM_PARTITION_OVERSUBSCRIBE=FORCE:4

submitted_batch_script="${staging_dir}/submitted-batch-script.sh"
batch_capture_stdout="${staging_dir}/batch-script-capture.stdout.log"
batch_capture_stderr="${staging_dir}/batch-script-capture.stderr.log"
if scontrol write batch_script "${job_id}" "${submitted_batch_script}" \
  > "${batch_capture_stdout}" 2> "${batch_capture_stderr}" \
  && [[ -s "${submitted_batch_script}" && ! -L "${submitted_batch_script}" ]]; then
  export MOONKVSIM_BATCH_SCRIPT_CAPTURE_STATUS=PASS
else
  export MOONKVSIM_BATCH_SCRIPT_CAPTURE_STATUS=FAIL
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=spooled_batch_script_capture_failed" >&2
  echo "MOONKVSIM_AIC_STAGING_PRESERVED=${staging_dir}" >&2
  exit 3
fi

export MOONKVSIM_CALIBRATION_SCRIPT_SHA256
if ! calibration_sha256_line="$(sha256sum -- "${staged_harness}")"; then
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=staged_harness_hash_failed" >&2
  echo "MOONKVSIM_AIC_STAGING_PRESERVED=${staging_dir}" >&2
  exit 3
fi
MOONKVSIM_CALIBRATION_SCRIPT_SHA256="${calibration_sha256_line%% *}"
export MOONKVSIM_SUBMITTED_BATCH_SCRIPT_SHA256
if ! submitted_sha256_line="$(sha256sum -- "${submitted_batch_script}")"; then
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=spooled_wrapper_hash_failed" >&2
  echo "MOONKVSIM_AIC_STAGING_PRESERVED=${staging_dir}" >&2
  exit 3
fi
MOONKVSIM_SUBMITTED_BATCH_SCRIPT_SHA256="${submitted_sha256_line%% *}"
if [[ ! "${MOONKVSIM_CALIBRATION_SCRIPT_SHA256}" =~ ^[0-9a-f]{64}$ \
  || ! "${MOONKVSIM_SUBMITTED_BATCH_SCRIPT_SHA256}" =~ ^[0-9a-f]{64}$ ]]; then
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=provenance_hash_malformed" >&2
  echo "MOONKVSIM_AIC_STAGING_PRESERVED=${staging_dir}" >&2
  exit 3
fi
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PYTHONHASHSEED=0
export VLLM_USE_V1=1
export VLLM_ENABLE_V1_MULTIPROCESSING=0
export VLLM_ATTENTION_BACKEND=FLASH_ATTN

if "${runtime_python}" "${staged_harness}" \
  --shape-plan "${staging_dir}/shape-plan.json" \
  --output-root "${final_dir}" \
  --staging-dir "${staging_dir}" \
  --source-lock "${staging_dir}/source-lock.json" \
  --support-audit "${staging_dir}/aiconfigurator-support.json"; then
  harness_status=0
else
  harness_status=$?
fi

leak_status=0
assigned_uuid_file="${staging_dir}/assigned-gpu-uuid.txt"
if [[ -s "${assigned_uuid_file}" && ! -L "${assigned_uuid_file}" ]]; then
  assigned_uuid="$(tr -d '[:space:]' < "${assigned_uuid_file}")"
  process_snapshot="${staging_dir}/wrapper-post-processes.txt"
  if nvidia-smi --query-compute-apps=pid,gpu_uuid --format=csv,noheader,nounits \
    > "${process_snapshot}" 2>&1; then
    query_status=0
  else
    query_status=$?
  fi
  if [[ ${query_status} -ne 0 ]]; then
    leak_status=4
  elif awk -F',' -v target="${assigned_uuid}" '
    {
      pid=$1; uuid=$2;
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", pid);
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", uuid);
      if (uuid == target && pid != "") found=1;
    }
    END { exit(found ? 0 : 1) }
  ' "${process_snapshot}"; then
    leak_status=4
  fi
elif [[ ${harness_status} -eq 0 || ${harness_status} -eq 7 ]]; then
  leak_status=4
fi

if [[ ${leak_status} -ne 0 ]]; then
  echo "MOONKVSIM_AIC_WRAPPER_ERROR=assigned_gpu_process_leak_or_unverifiable" >&2
  echo "MOONKVSIM_AIC_STAGING_PRESERVED=${staging_dir}" >&2
  exit 4
fi
if [[ ${harness_status} -ne 0 && ${harness_status} -ne 7 ]]; then
  echo "MOONKVSIM_AIC_STAGING_PRESERVED=${staging_dir}" >&2
  exit "${harness_status}"
fi

# Delete only the exact mktemp tree created above, after publication and the
# wrapper-level leak audit.  Failed runs retain staging for diagnosis.
case "${staging_dir}" in
  "/tmp/moonkvsim-aic-${job_id}."??????) rm -rf -- "${staging_dir}" ;;
  *)
    echo "MOONKVSIM_AIC_WRAPPER_ERROR=refusing_unsafe_staging_cleanup" >&2
    exit 8
    ;;
esac
exit "${harness_status}"
