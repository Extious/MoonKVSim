"""Scoped upload/status/sync helpers. This helper never submits a GPU job."""
import argparse
import io
import json
from pathlib import Path
import shlex
import subprocess
import tarfile

from transfer_weights import SSH

ROOT = Path(__file__).resolve().parent.parent
REMOTE = "/home/bingxing2/home/scx8q31/aegiskv_reuse_qwen25_1m_20260919"
FILES = ["sg_sparse_backend.py", "layerwise_restore.py", "measure_prefill_sparse.py",
         "launch_prefill_sparse.py", "blsc/build_sparse_cpu.py", "blsc/budget_submit.py",
         "blsc/submit_prefill_sparse.py", "blsc/run_prefill_sparse.sbatch",
         "sparse-config/manifest.json", "sparse-config/model2path.py",
         "sparse-config/Qwen2.5_7B_Instruct_1M.json", "sparse-config/LICENSE",
         "SPARSE_OVERLAP_PROTOCOL.md", "sharedfs_io.py", "SHAREDFS_PROTOCOL.md", "blsc/cleanup_sharedfs.py"]


def remote(code):
    return subprocess.check_output(SSH+["python3 -c "+shlex.quote(code)], text=True, timeout=55)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("upload", "build", "status", "sync"))
    args = ap.parse_args()
    if args.action == "upload":
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as archive:
            for name in FILES:
                archive.add(ROOT/name, arcname=name, recursive=False)
        subprocess.run(SSH+["tar -xf - -C "+shlex.quote(REMOTE)], input=buf.getvalue(), check=True, timeout=55)
        print(json.dumps({"uploaded": FILES}))
    elif args.action == "build":
        shell = '''cd ROOT_PLACEHOLDER
export CUDA_VISIBLE_DEVICES="" CUDA_HOME="$PWD/setup/cuda-12.8" CUDA_PATH="$PWD/setup/cuda-12.8"
export PATH="$PWD/.venv/bin:$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/lib:${LD_LIBRARY_PATH:-}"
export CPATH="$CUDA_HOME/include"
for AEGIS_SPARSE_INC in /home/bingxing2/home/scx8q31/miniconda3/envs/megatron-reft/lib/python3.12/site-packages/nvidia/*/include; do
 if [ -d "$AEGIS_SPARSE_INC" ]; then CPATH="$CPATH:$AEGIS_SPARSE_INC"; fi
done
export C_INCLUDE_PATH="$CPATH" CPLUS_INCLUDE_PATH="$CPATH"
mkdir -p setup/sparse-sm80
if [ -f setup/sparse-sm80/build.log ]; then cp setup/sparse-sm80/build.log "setup/sparse-sm80/build-prior-$(date +%s).log"; fi
nohup .venv/bin/python -u blsc/build_sparse_cpu.py > setup/sparse-sm80/build.log 2>&1 < /dev/null &
printf '%s\\n' "$!"
'''.replace("ROOT_PLACEHOLDER", shlex.quote(REMOTE))
        print(subprocess.check_output(SSH+["bash -c "+shlex.quote(shell)], text=True, timeout=55))
    elif args.action == "status":
        print(remote(f'''import pathlib,json,subprocess
r=pathlib.Path({REMOTE!r});p=r/"setup/sparse-sm80"
print("SPARSE_READY",(p/"READY.json").exists())
if not (p/"READY.json").exists() and (p/"build.log").exists():
 a=(p/"build.log").read_text().splitlines()
 errors=[x for x in a if "error:" in x or "Error:" in x or "FAILED:" in x]
 print("\\n".join(errors[:8] if errors else [x[:200] for x in a[-4:]]))
print(subprocess.check_output(["squeue","-h","-u","scx8q31","-n","aegis-qwen1m-budget","-o","%i|%j|%T|%M|%R"],text=True))
b=json.loads((r/"blsc/budget.json").read_text());print("CAP",b["budget_gpu_seconds"])
jobs=[x for x in b["jobs"] if x.get("purpose","").startswith("sparse Prefill")]
for j in jobs[-1:]:
 p=r/"blsc/results"/j.get("job_id","")
 print("JOB",j.get("job_id"),"COMPLETE",(p/"COMPLETE").exists())
 if (p/"progress.jsonl").exists():print("\\n".join((p/"progress.jsonl").read_text().splitlines()[-3:]))
 for f in p.glob("failure-rank*.json"):print(f.name,f.read_text())
 log=r/"blsc/logs"/f"aegis-qwen1m-budget-{{j.get('job_id')}}.log"
 if log.exists():print("\\n".join(log.read_text(errors="replace").splitlines()[-4:]))
'''))
    else:
        response = remote(f'''import pathlib,json,sys,subprocess
r=pathlib.Path({REMOTE!r});sys.path.insert(0,str(r/"blsc"))
from budget_submit import reconcile,write_atomic
b=json.loads((r/"blsc/budget.json").read_text());ids=[j["job_id"] for j in b["jobs"] if j.get("job_id")]
report=subprocess.check_output(["sacct","-X","-n","-P","-j",",".join(ids),"--format=JobIDRaw,State,ElapsedRaw,AllocTRES"],text=True)
reconcile(b,report);write_atomic(r/"blsc/budget.json",b)
paths=[r/"blsc/budget.json"]+list((r/"setup/sparse-sm80").glob("*.json"))+list((r/"setup/sparse-sm80").glob("*.log"))+list((r/"setup/sparse-sm80").glob("*.py"))
for j in b["jobs"]:
 if j.get("purpose","").startswith("sparse Prefill") and j.get("job_id"):
  paths+=list((r/"blsc/results"/j["job_id"]).glob("*"))
  paths+=list((r/"sparse-archive"/j["job_id"]).rglob("*"))
  paths.append(r/"blsc/logs"/f"aegis-qwen1m-budget-{{j['job_id']}}.log")
files={{str(p.relative_to(r)):p.read_text(errors="replace") for p in paths if p.is_file() and p.stat().st_size<16*1024**2}}
print("AEGIS_SPARSE_JSON\\n"+json.dumps(files))
''')
        files = json.loads(response.split("AEGIS_SPARSE_JSON\n", 1)[1])
        for name, content in files.items():
            p = Path(name)
            assert not p.is_absolute() and ".." not in p.parts
            dest = ROOT/p if p.parts[0] in ("blsc", "sparse-archive") else ROOT/"blsc"/p
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
        b = json.loads((ROOT/"blsc/budget.json").read_text())
        used = b["prior_inventory_gpu_seconds"]+sum(j["actual_gpu_seconds"] if j.get("terminal") else j["reserved_gpu_seconds"] for j in b["jobs"])
        print(json.dumps({"files_synced": len(files), "used_or_reserved_gpu_seconds": used,
                          "remaining_gpu_seconds": b["budget_gpu_seconds"]-used,
                          "recent_jobs": [{k:j.get(k) for k in ("job_id","last_slurm_state","actual_gpu_seconds")} for j in b["jobs"][-3:]]}))


if __name__ == "__main__":
    main()
