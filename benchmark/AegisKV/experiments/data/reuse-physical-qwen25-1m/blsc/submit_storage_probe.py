"""Budgeted 1-GPU, 1-minute read-only local-storage inventory; exits promptly."""
import fcntl
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import time

from budget_submit import reconcile, reservation, used_or_reserved, write_atomic

root = Path(__file__).resolve().parent
with (root / "budget.lock").open("a") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    ledger_path = root / "budget.json"
    ledger = json.loads(ledger_path.read_text())
    ids = [j["job_id"] for j in ledger["jobs"] if j.get("job_id")]
    report = subprocess.check_output(["sacct", "-X", "-n", "-P", "-j", ",".join(ids),
                                     "--format=JobIDRaw,State,ElapsedRaw,AllocTRES"], text=True, timeout=20)
    reconcile(ledger, report)
    write_atomic(ledger_path, ledger)
    seconds = reservation(ledger, 1, 1)
    names = ["probe_local_storage.py", "submit_storage_probe.py"]
    job = dict(submitted_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               requested_gpus=1, time_limit_minutes=1, reserved_gpu_seconds=seconds,
               terminal=False, status="submission_pending",
               purpose="sparse Prefill SSD feasibility: read-only local-storage inventory",
               source_sha256={"blsc/" + n: hashlib.sha256((root/n).read_bytes()).hexdigest() for n in names})
    ledger["jobs"].append(job)
    write_atomic(ledger_path, ledger)
    script = "#!/bin/bash\nset -euo pipefail\nexec python3 " + shlex.quote(str(root / "probe_local_storage.py")) + "\n"
    reply = subprocess.check_output([
        "sbatch", "--parsable", "--partition=gpu", "--nodes=1", "--ntasks=1",
        "--gpus-per-node=1", "--cpus-per-task=32", "--time=1", "--no-requeue",
        "--exclude=paraai-n32-h-01-agent-4", "--job-name=aegis-qwen1m-budget",
        "--output=logs/%x-%j.log"], cwd=root, text=True, input=script).strip()
    jid = reply.split(";")[0]
    assert jid.isdigit(), reply
    job.update(job_id=jid, status="submitted")
    write_atomic(ledger_path, ledger)
    archive = root.parent / "sparse-archive" / jid / "blsc"
    archive.mkdir(parents=True, exist_ok=True)
    for n in names:
        (archive/n).write_bytes((root/n).read_bytes())
    print(json.dumps(dict(job=job, used_or_reserved_gpu_seconds=used_or_reserved(ledger))), flush=True)
