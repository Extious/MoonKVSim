"""Reserve a sparse three-path run inside the user-authorized 5.5 GPU-hours."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import time

from budget_submit import reconcile, reservation, used_or_reserved, write_atomic

root = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--minutes", type=int, default=22)
ap.add_argument("--pilot", action="store_true")
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--head-group", type=int, default=2, choices=(1, 2, 4, 7))
ap.add_argument("--sharedfs", action="store_true")
args = ap.parse_args()
minutes = 4 if args.pilot else args.minutes
assert 1 <= minutes <= 30
contexts = "8192,65536" if args.pilot else "8192,65536,262144,1010000"
with (root/"budget.lock").open("a") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    ledger_path = root/"budget.json"
    ledger = json.loads(ledger_path.read_text())
    ids = [j["job_id"] for j in ledger["jobs"] if j.get("job_id")]
    report = subprocess.check_output(["sacct", "-X", "-n", "-P", "-j", ",".join(ids),
                                     "--format=JobIDRaw,State,ElapsedRaw,AllocTRES"], text=True, timeout=20)
    reconcile(ledger, report)
    write_atomic(ledger_path, ledger)
    assert ledger["budget_gpu_seconds"] == 19800
    seconds = reservation(ledger, 2, minutes)
    ready = json.loads((root/"READY.json").read_text())
    sparse = json.loads((root.parent/"setup/sparse-sm80/READY.json").read_text())
    assert sparse["architecture"] == "sm_80" and sparse["cpu_build_only"]
    checks = [(x["library"], x["library_sha256"]) for x in ready["sm80_libraries"].values()]
    checks += [(sparse["library"], sparse["library_sha256"]),
               (sparse["wrapper"], sparse["wrapper_sha256"])]
    for path, digest in checks:
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path
    names = ["measure_prefill_sparse.py", "launch_prefill_sparse.py", "sg_sparse_backend.py",
             "layerwise_restore.py", "sg_backend.py", "dca_grouped.py", "measure.py",
             "measure_prefill_optimized.py", "sparse-config/Qwen2.5_7B_Instruct_1M.json",
             "sparse-config/manifest.json", "blsc/run_prefill_sparse.sbatch",
             "blsc/submit_prefill_sparse.py", "blsc/budget_submit.py"]
    if args.sharedfs:
        names += ["sharedfs_io.py", "blsc/cleanup_sharedfs.py"]
    sources = {name: hashlib.sha256((root.parent/name).read_bytes()).hexdigest() for name in names}
    job = dict(submitted_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               requested_gpus=2, time_limit_minutes=minutes, reserved_gpu_seconds=seconds,
               terminal=False, status="submission_pending",
               purpose=("sparse Prefill four paths including SharedFS, serial DRAM/storage, one storage read per context"
                        if args.sharedfs else "sparse Prefill three paths, serial DRAM only"),
               contexts=contexts, pilot=args.pilot, sparse_head_group=args.head_group,
               source_sha256=sources, sparse_library_sha256=sparse["library_sha256"])
    if args.sharedfs:
        job["sharedfs_root"] = str(root.parent/"sharedfs-kv")
    if args.dry_run:
        print(json.dumps({"dry_run": True, "planned_job": job,
                          "used_gpu_seconds": used_or_reserved(ledger),
                          "projected_reserved_gpu_seconds": used_or_reserved(ledger)+seconds}))
        raise SystemExit(0)
    ledger["jobs"].append(job)
    write_atomic(ledger_path, ledger)
    env = os.environ.copy()
    env.update(AEGIS_ROOT=str(root.parent), AEGIS_PYTHON=ready["python"],
               AEGIS_MODEL=ready["model"], TP="2", AEGIS_CONTEXTS=contexts,
               AEGIS_SPARSE_HEAD_GROUP=str(args.head_group))
    if args.sharedfs:
        env["AEGIS_SHARED_FS"] = job["sharedfs_root"]
    reply = subprocess.check_output([
        "sbatch", "--parsable", "--partition=gpu", "--nodes=1", "--ntasks=1",
        "--gpus-per-node=2", "--cpus-per-task=64", f"--time={minutes}", "--no-requeue",
        "--signal=B:TERM@20", "--exclude=paraai-n32-h-01-agent-4",
        "--job-name=aegis-qwen1m-budget", "--output=logs/%x-%j.log",
        str(root/"run_prefill_sparse.sbatch")], cwd=root, env=env, text=True).strip()
    jid = reply.split(";")[0]
    assert jid.isdigit(), reply
    job.update(job_id=jid, status="submitted")
    write_atomic(ledger_path, ledger)
    archive = root.parent/"sparse-archive"/jid
    for name, digest in sources.items():
        dest = archive/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root.parent/name, dest)
    (archive/"source-sha256.json").write_text(json.dumps(sources, indent=2)+"\n")
    print(json.dumps({"job": job, "used_or_reserved_gpu_seconds": used_or_reserved(ledger)}))
