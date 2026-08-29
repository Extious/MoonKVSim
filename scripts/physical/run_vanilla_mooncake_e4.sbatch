#!/usr/bin/env bash
#SBATCH --job-name=moonkv-vanilla-e4
#SBATCH --partition=debug
#SBATCH --nodelist=gpu10
#SBATCH --gres=gpu:rtx4090:2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=160G
#SBATCH --time=01:30:00
#SBATCH --exclusive
#SBATCH --output=benchmark/physical/vanilla-mooncake-e4/slurm-%j.wrapper.out
#SBATCH --error=benchmark/physical/vanilla-mooncake-e4/slurm-%j.wrapper.err

set -uo pipefail

expected_repo_root="/home/comp/zhanzhao/MoonKVSim"
submitted_root="${SLURM_SUBMIT_DIR:-}"
if [[ -z "${submitted_root}" || ! -d "${submitted_root}" ]]; then
  echo "MOONKVSIM_E4_WRAPPER_ERROR=missing_slurm_submit_dir" >&2
  exit 63
fi
repo_root="$(cd -- "${submitted_root}" && pwd -P)"
if [[ "${repo_root}" != "${expected_repo_root}" ]]; then
  echo "MOONKVSIM_E4_WRAPPER_ERROR=unexpected_submit_dir:${repo_root}" >&2
  exit 63
fi

runtime_python="/home/comp/zhanzhao/Mooncake/aegiskv/.venv-vllm-sm89/bin/python"
vllm_build_manifest="/home/comp/zhanzhao/Mooncake/aegiskv/paper/fallback_4090/runtime-build-manifest.json"
harness_source="${repo_root}/scripts/physical/vanilla_mooncake_e4.py"
schema_source="${repo_root}/benchmark/physical/vanilla-mooncake-e4/result.schema.json"
artifact_root="${repo_root}/benchmark/physical/vanilla-mooncake-e4"
clean_build_dir="${MOONKVSIM_CLEAN_BUILD_DIR:-${artifact_root}/clean-build}"
build_manifest="${clean_build_dir}/build-manifest.json"
native_runtime_dir="${clean_build_dir}/native-runtime"
preflight_record="${MOONKVSIM_PREFLIGHT_RECORD:-}"
job_id="${SLURM_JOB_ID:-}"

if [[ -z "${job_id}" || ! "${job_id}" =~ ^[0-9]+$ ]]; then
  echo "MOONKVSIM_E4_WRAPPER_ERROR=missing_numeric_slurm_job_id" >&2
  exit 64
fi
if [[ ! -x "${runtime_python}" || ! -f "${vllm_build_manifest}" \
  || -L "${vllm_build_manifest}" || ! -f "${harness_source}" || ! -f "${schema_source}" ]]; then
  echo "MOONKVSIM_E4_WRAPPER_ERROR=missing_pinned_runtime_or_repo_input" >&2
  exit 65
fi
if [[ ! -d "${clean_build_dir}" || -L "${clean_build_dir}" ]]; then
  echo "MOONKVSIM_E4_WRAPPER_ERROR=unsafe_or_missing_clean_build:${clean_build_dir}" >&2
  exit 66
fi
if [[ ! -f "${build_manifest}" || ! -f "${clean_build_dir}/PUBLICATION_COMPLETE.json" \
  || ! -f "${clean_build_dir}/native-runtime-manifest.json" \
  || ! -d "${native_runtime_dir}" || -L "${native_runtime_dir}" ]]; then
  echo "MOONKVSIM_E4_WRAPPER_ERROR=incomplete_clean_build" >&2
  exit 66
fi
if [[ -z "${preflight_record}" || ! -f "${preflight_record}" || -L "${preflight_record}" ]]; then
  echo "MOONKVSIM_E4_WRAPPER_ERROR=missing_or_unsafe_preflight_record" >&2
  exit 68
fi
if [[ -e "${clean_build_dir}/BUILD_INCOMPLETE" || -e "${clean_build_dir}/PUBLICATION_INCOMPLETE" ]]; then
  echo "MOONKVSIM_E4_WRAPPER_ERROR=clean_build_has_incomplete_marker" >&2
  exit 66
fi
if ! (cd -- "${clean_build_dir}" && sha256sum --check --strict SHA256SUMS); then
  echo "MOONKVSIM_E4_WRAPPER_ERROR=clean_build_checksum_failure" >&2
  exit 67
fi

mapfile -t clean_wheels < <(find "${clean_build_dir}" -maxdepth 1 -type f -name '*.whl' -print | sort)
if [[ "${#clean_wheels[@]}" -ne 1 ]]; then
  echo "MOONKVSIM_E4_WRAPPER_ERROR=expected_one_clean_wheel:${#clean_wheels[@]}" >&2
  exit 67
fi
clean_wheel="${clean_wheels[0]}"

mkdir -p -- "${artifact_root}"
final_dir="${artifact_root}/${job_id}"
if [[ -e "${final_dir}" || -L "${final_dir}" ]]; then
  echo "MOONKVSIM_E4_WRAPPER_ERROR=refusing_existing_run:${final_dir}" >&2
  exit 73
fi
if ! staging_dir="$(mktemp -d "${artifact_root}/.${job_id}.staging.XXXXXX")"; then
  echo "MOONKVSIM_E4_WRAPPER_ERROR=cannot_create_staging_directory" >&2
  exit 74
fi
printf '%s\n' 'Physical run is not yet atomically published.' > "${staging_dir}/PUBLICATION_INCOMPLETE"

job_tmp_parent="${SLURM_TMPDIR:-/tmp}"
if ! overlay_root="$(mktemp -d "${job_tmp_parent%/}/moonkvsim-vanilla-e4-${job_id}.XXXXXX")"; then
  echo "MOONKVSIM_E4_WRAPPER_ERROR=cannot_create_overlay_directory" >&2
  exit 74
fi
cleanup_overlay() {
  if [[ -n "${overlay_root:-}" && -d "${overlay_root}" && ! -L "${overlay_root}" ]]; then
    rm -rf -- "${overlay_root}"
  fi
}
trap cleanup_overlay EXIT

harness_snapshot="${staging_dir}/vanilla_mooncake_e4.py"
schema_snapshot="${staging_dir}/result.schema.json"
preflight_snapshot="${staging_dir}/submission-preflight.json"
if ! cp -- "${harness_source}" "${harness_snapshot}" \
  || ! cp -- "${schema_source}" "${schema_snapshot}" \
  || ! cp -- "${preflight_record}" "${preflight_snapshot}" \
  || ! cp -- "${build_manifest}" "${staging_dir}/clean-build-manifest.json" \
  || ! cp -- "${clean_build_dir}/PUBLICATION_COMPLETE.json" \
    "${staging_dir}/clean-build-PUBLICATION_COMPLETE.json" \
  || ! cp -- "${clean_build_dir}/SHA256SUMS" "${staging_dir}/clean-build-SHA256SUMS" \
  || ! cp -- "${clean_build_dir}/native-runtime-manifest.json" \
    "${staging_dir}/clean-build-native-runtime-manifest.json" \
  || ! cp -- "${clean_build_dir}/elf-runtime-audit.json" \
    "${staging_dir}/clean-build-elf-runtime-audit.json" \
  || ! cp -- "${vllm_build_manifest}" "${staging_dir}/pinned-vllm-build-manifest.json"; then
  echo "MOONKVSIM_E4_WRAPPER_ERROR=critical_source_snapshot_failure:${staging_dir}" >&2
  exit 74
fi
for provenance_name in source-tree-manifest.json native-dependency-manifest.json \
  build-constraints.txt \
  build-tool-freeze.pre-wheel.txt build-tool-freeze.txt CMakeCache.txt; do
  if [[ -f "${clean_build_dir}/${provenance_name}" && ! -L "${clean_build_dir}/${provenance_name}" ]]; then
    cp -- "${clean_build_dir}/${provenance_name}" \
      "${staging_dir}/clean-build-${provenance_name}"
  fi
done
chmod 0755 -- "${harness_snapshot}"
harness_sha256="$(sha256sum -- "${harness_snapshot}" | awk '{print $1}')"
schema_sha256="$(sha256sum -- "${schema_snapshot}" | awk '{print $1}')"
clean_wheel_sha256="$(sha256sum -- "${clean_wheel}" | awk '{print $1}')"
build_manifest_sha256="$(sha256sum -- "${build_manifest}" | awk '{print $1}')"
preflight_record_sha256="$(sha256sum -- "${preflight_record}" | awk '{print $1}')"

batch_capture_stdout="${staging_dir}/batch-script-capture.stdout.log"
batch_capture_stderr="${staging_dir}/batch-script-capture.stderr.log"
submitted_batch_script="${staging_dir}/submitted-batch-script.sh"
if scontrol write batch_script "${job_id}" "${submitted_batch_script}" \
  > "${batch_capture_stdout}" 2> "${batch_capture_stderr}" \
  && [[ -s "${submitted_batch_script}" ]]; then
  batch_capture_status="PASS"
  submitted_batch_sha256="$(sha256sum -- "${submitted_batch_script}" | awk '{print $1}')"
else
  batch_capture_status="FAIL"
  submitted_batch_sha256=""
fi

preflight_binding_status="FAIL"
if [[ "${batch_capture_status}" == "PASS" ]] && \
  "${runtime_python}" - "${preflight_snapshot}" "${repo_root}" \
    "${harness_snapshot}" "${schema_snapshot}" "${clean_build_dir}" \
    "${clean_wheel}" "${submitted_batch_script}" <<'PY'
import hashlib
import json
import pathlib
import sys


def digest(path):
    value = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


record_path, repo, harness, schema, clean_build, wheel, batch = map(pathlib.Path, sys.argv[1:])
record = json.loads(record_path.read_text(encoding="utf-8"))
vllm_record = record.get("pinned_vllm", {})
vllm_manifest = pathlib.Path(vllm_record.get("manifest", ""))
vllm_wheel = pathlib.Path(vllm_record.get("wheel", ""))
vllm_runtime = pathlib.Path(vllm_record.get("runtime_resolved", ""))
checks = {
    "status": (record.get("status"), "READY_TO_SUBMIT"),
    "submission_allowed": (record.get("submission_allowed"), True),
    "submitted": (record.get("intended_submission", {}).get("submitted"), False),
    "submit_directory": (
        record.get("intended_submission", {}).get("submit_directory"),
        str(repo.resolve()),
    ),
    "harness_sha256": (
        record.get("inputs", {}).get("harness", {}).get("sha256"),
        digest(harness),
    ),
    "schema_sha256": (
        record.get("inputs", {}).get("result_schema", {}).get("sha256"),
        digest(schema),
    ),
    "batch_sha256": (
        record.get("inputs", {}).get("sbatch", {}).get("sha256"),
        digest(batch),
    ),
    "clean_build_directory": (
        record.get("clean_build", {}).get("directory"),
        str(clean_build.resolve()),
    ),
    "clean_wheel_sha256": (
        record.get("clean_build", {}).get("wheel_sha256"),
        digest(wheel),
    ),
    "clean_manifest_sha256": (
        record.get("clean_build", {}).get("manifest_sha256"),
        digest(clean_build / "build-manifest.json"),
    ),
    "clean_sha256sums_sha256": (
        record.get("clean_build", {}).get("sha256sums_sha256"),
        digest(clean_build / "SHA256SUMS"),
    ),
    "clean_native_dependency_manifest_sha256": (
        record.get("clean_build", {}).get("native_dependency_manifest_sha256"),
        digest(clean_build / "native-dependency-manifest.json"),
    ),
    "clean_native_runtime_directory": (
        record.get("clean_build", {}).get("native_runtime_directory"),
        str((clean_build / "native-runtime").resolve()),
    ),
    "clean_native_runtime_manifest_sha256": (
        record.get("clean_build", {}).get("native_runtime_manifest_sha256"),
        digest(clean_build / "native-runtime-manifest.json"),
    ),
    "clean_elf_runtime_audit_sha256": (
        record.get("clean_build", {}).get("elf_runtime_audit_sha256"),
        digest(clean_build / "elf-runtime-audit.json"),
    ),
    "vllm_manifest_sha256": (
        vllm_record.get("manifest_sha256"),
        digest(vllm_manifest),
    ),
    "vllm_wheel_sha256": (
        vllm_record.get("wheel_sha256"),
        digest(vllm_wheel),
    ),
    "vllm_runtime_sha256": (
        vllm_record.get("runtime_sha256"),
        digest(vllm_runtime),
    ),
}
mismatches = {
    key: {"observed": observed, "expected": expected}
    for key, (observed, expected) in checks.items()
    if observed != expected
}
if mismatches:
    raise SystemExit("preflight binding mismatch: " + json.dumps(mismatches, sort_keys=True))
PY
then
  preflight_binding_status="PASS"
fi

export PYTHONHASHSEED=0
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export VLLM_USE_V1=1
export PYTHONPATH="${overlay_root}"
export LD_LIBRARY_PATH="${native_runtime_dir}:${native_runtime_dir}/libibverbs"

{
  echo "schema=moonkvsim.vanilla_mooncake_e4_runtime.v1"
  echo "observed_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "hostname=$(hostname)"
  echo "slurm_job_id=${job_id}"
  echo "slurm_partition=${SLURM_JOB_PARTITION:-}"
  echo "slurm_node=${SLURMD_NODENAME:-}"
  echo "slurm_job_gpus=${SLURM_JOB_GPUS:-}"
  echo "cuda_visible_devices=${CUDA_VISIBLE_DEVICES:-}"
  echo "slurm_cpus_per_task=${SLURM_CPUS_PER_TASK:-}"
  echo "slurm_mem_per_node=${SLURM_MEM_PER_NODE:-}"
  echo "runtime_python=${runtime_python}"
  echo "harness_source=${harness_source}"
  echo "harness_snapshot_sha256=${harness_sha256}"
  echo "schema_snapshot_sha256=${schema_sha256}"
  echo "clean_build_dir=${clean_build_dir}"
  echo "clean_wheel=${clean_wheel}"
  echo "clean_wheel_sha256=${clean_wheel_sha256}"
  echo "build_manifest_sha256=${build_manifest_sha256}"
  echo "native_runtime_dir=${native_runtime_dir}"
  echo "ld_library_path=${LD_LIBRARY_PATH}"
  echo "pythonpath=${PYTHONPATH}"
  echo "preflight_record=${preflight_record}"
  echo "preflight_record_sha256=${preflight_record_sha256}"
  echo "preflight_binding_status=${preflight_binding_status}"
  echo "batch_capture_status=${batch_capture_status}"
  echo "submitted_batch_script_sha256=${submitted_batch_sha256}"
} > "${staging_dir}/runtime.txt"

{
  echo "# scontrol show job -dd -o ${job_id}"
  scontrol show job -dd -o "${job_id}" 2>&1 || true
  echo "# sacct -X -j ${job_id}"
  sacct -X -j "${job_id}" \
    --format=JobIDRaw,JobName,Partition,State,AllocTRES,NodeList,Start,Elapsed,Timelimit \
    --parsable2 2>&1 || true
} > "${staging_dir}/slurm-job.txt"

if [[ "${batch_capture_status}" != "PASS" ]]; then
  printf '%s\n' 'Slurm-spooled batch script capture failed.' \
    > "${staging_dir}/BATCH_SCRIPT_CAPTURE_FAILED.txt"
  wrapper_status=68
elif [[ "${preflight_binding_status}" != "PASS" ]]; then
  printf '%s\n' 'Preflight record does not bind the submitted sources/build.' \
    > "${staging_dir}/PREFLIGHT_BINDING_FAILED.txt"
  wrapper_status=68
else
  aegis_environment="$(env | awk -F= 'toupper($1) ~ /AEGIS/ {print}')"
  if [[ -n "${aegis_environment}" ]]; then
    printf '%s\n' "${aegis_environment}" \
      > "${staging_dir}/forbidden-aegis-environment.txt"
    wrapper_status=69
  else
    "${runtime_python}" -m pip install \
      --disable-pip-version-check \
      --no-deps \
      --no-compile \
      --target "${overlay_root}" \
      "${clean_wheel}" \
      > "${staging_dir}/clean-overlay-install.stdout.log" \
      2> "${staging_dir}/clean-overlay-install.stderr.log"
    wrapper_status=$?
  fi
fi

if [[ "${wrapper_status:-1}" -eq 0 ]]; then
  "${runtime_python}" "${harness_snapshot}" \
    --artifact-dir "${staging_dir}" \
    --clean-wheel "${clean_wheel}" \
    --build-manifest "${build_manifest}" \
    --overlay "${overlay_root}" \
    > "${staging_dir}/harness.stdout.log" \
    2> "${staging_dir}/harness.stderr.log"
  harness_status=$?
else
  harness_status="${wrapper_status}"
  "${runtime_python}" -c \
    'import json,sys; json.dump({"schema":"moonkvsim.vanilla_mooncake_e4.v1","status":"FAIL","evidence_level":"NONE","paper_ready":False,"error":"wrapper preflight failed","wrapper_status":int(sys.argv[2])},open(sys.argv[1],"x"),sort_keys=True,separators=(",",":")); open(sys.argv[1],"a").write("\n")' \
    "${staging_dir}/result.json" "${wrapper_status}"
fi
printf '%s\n' "${harness_status}" > "${staging_dir}/harness-exit-code.txt"

schema_status=0
if [[ -s "${staging_dir}/result.json" ]]; then
  "${runtime_python}" -c \
    'import json,jsonschema,sys; jsonschema.Draft202012Validator.check_schema(json.load(open(sys.argv[1]))); jsonschema.validate(json.load(open(sys.argv[2])),json.load(open(sys.argv[1])))' \
    "${schema_snapshot}" "${staging_dir}/result.json" \
    > "${staging_dir}/schema-validation.stdout.log" \
    2> "${staging_dir}/schema-validation.stderr.log"
  schema_status=$?
else
  schema_status=74
  printf '%s\n' 'result.json is missing' > "${staging_dir}/schema-validation.stderr.log"
fi
printf '%s\n' "${schema_status}" > "${staging_dir}/schema-validation-exit-code.txt"

{
  echo "# scontrol show job -dd -o ${job_id} (post-run)"
  scontrol show job -dd -o "${job_id}" 2>&1 || true
  echo "# sstat -j ${job_id}.batch (post-run)"
  sstat -j "${job_id}.batch" \
    --format=JobID,AveCPU,MaxRSS,MaxVMSize,AveRSS \
    --parsable2 2>&1 || true
} >> "${staging_dir}/slurm-job.txt"

publication_status="PASS"
final_status="${harness_status}"
if [[ "${harness_status}" -ne 0 || "${schema_status}" -ne 0 ]]; then
  publication_status="FAIL"
  if [[ "${final_status}" -eq 0 ]]; then
    final_status="${schema_status}"
  fi
fi
if ! "${runtime_python}" -c \
  'import json,sys; value={"schema":"moonkvsim.vanilla_mooncake_e4_publication.v1","publication":"COMPLETE","status":sys.argv[2],"harness_exit_code":int(sys.argv[3]),"schema_exit_code":int(sys.argv[4])}; open(sys.argv[1],"x").write(json.dumps(value,sort_keys=True,separators=(",",":"))+"\n")' \
  "${staging_dir}/PUBLICATION_COMPLETE.json" "${publication_status}" \
  "${harness_status}" "${schema_status}"; then
  echo "MOONKVSIM_E4_WRAPPER_ERROR=completion_marker_creation_failed:${staging_dir}" >&2
  exit 75
fi
if ! rm -- "${staging_dir}/PUBLICATION_INCOMPLETE"; then
  rm -f -- "${staging_dir}/PUBLICATION_COMPLETE.json"
  echo "MOONKVSIM_E4_WRAPPER_ERROR=incomplete_marker_removal_failed:${staging_dir}" >&2
  exit 75
fi

(
  cd -- "${staging_dir}" || exit 1
  while IFS= read -r -d '' artifact; do
    sha256sum -- "${artifact}"
  done < <(find . -type f ! -name SHA256SUMS -print0 | sort -z)
) > "${staging_dir}/SHA256SUMS"
checksum_status=$?
if [[ "${checksum_status}" -ne 0 ]]; then
  rm -f -- "${staging_dir}/PUBLICATION_COMPLETE.json"
  printf '%s\n' 'Physical run publication failed during checksum generation.' \
    > "${staging_dir}/PUBLICATION_INCOMPLETE"
  echo "MOONKVSIM_E4_WRAPPER_ERROR=checksum_generation_failed:${staging_dir}" >&2
  exit 75
fi

mv -T -- "${staging_dir}" "${final_dir}"
publish_status=$?
if [[ "${publish_status}" -ne 0 ]]; then
  rm -f -- "${staging_dir}/PUBLICATION_COMPLETE.json"
  printf '%s\n' 'Physical run publication failed during atomic rename.' \
    > "${staging_dir}/PUBLICATION_INCOMPLETE"
  echo "MOONKVSIM_E4_WRAPPER_ERROR=atomic_publication_failed:${staging_dir}" >&2
  exit 76
fi

exit "${final_status}"
