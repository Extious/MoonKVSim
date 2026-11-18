#!/usr/bin/env python3
"""Reserve GPU time before sbatch; reconcile only terminal Slurm allocations.

The remote ledger is authoritative. Unknown/active jobs keep their full reserved
time. A lost sbatch reply blocks further submission until reconciled manually.
No automatic retries, job chains, requeue, or allocations for installation.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY",
            "NODE_FAIL", "PREEMPTED", "BOOT_FAIL", "DEADLINE", "REVOKED"}


def write_atomic(path, value):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(value, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def reconcile(ledger, accounting):
    rows = {}
    for line in accounting.splitlines():
        fields = line.strip().split("|")
        if len(fields) < 4 or not fields[0].isdigit():
            continue
        rows[fields[0]] = fields
    for job in ledger["jobs"]:
        row = rows.get(job.get("job_id"))
        if not row:
            continue
        state = row[1].split()[0].rstrip("+")
        job["last_slurm_state"] = state
        if state not in TERMINAL:
            continue
        elapsed = int(row[2])
        tres = dict(x.split("=", 1) for x in row[3].split(",") if "=" in x)
        allocated = tres.get("gres/gpu")
        # A cancelled pending job has no allocation and consumes no GPU time.
        # Otherwise, missing allocation information does not release credit.
        if allocated is None and elapsed != 0:
            continue
        gpus = int(allocated) if allocated is not None else 0
        job.update(terminal=True, elapsed_seconds=elapsed, allocated_gpus=gpus,
                   actual_gpu_seconds=elapsed * gpus)


def used_or_reserved(ledger):
    return ledger["prior_inventory_gpu_seconds"] + sum(
        j["actual_gpu_seconds"] if j.get("terminal") else j["reserved_gpu_seconds"]
        for j in ledger["jobs"])


def reservation(ledger, gpus, minutes):
    if gpus not in (1, 2, 4) or minutes < 1:
        raise ValueError("Use 1, 2, or 4 GPUs and a positive integer time limit")
    if any(not j.get("terminal") for j in ledger["jobs"]):
        raise ValueError("A submitted/unresolved job exists; reconcile it first")
    seconds = gpus * (minutes * 60 + ledger["termination_margin_seconds_per_gpu"])
    if used_or_reserved(ledger) + seconds > ledger["budget_gpu_seconds"]:
        raise ValueError(f"Request would exceed the authorized {ledger['budget_gpu_seconds']/3600:g} GPU-hour budget, including shutdown margin")
    return seconds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["status", "submit"])
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument("--gpus", type=int, default=2)
    ap.add_argument("--minutes", type=int, default=2)
    ap.add_argument("--contexts", default="8192")
    ap.add_argument("--inputs", type=int, default=1)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--node", help="Restrict to a previously verified compatible node")
    ap.add_argument("--exclude", default='', help="Comma-separated known-incompatible nodes")
    args = ap.parse_args()
    root = args.root.resolve()
    path = root / "budget.json"
    with (root / "budget.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger = json.loads(path.read_text())
        assert ledger["budget_gpu_seconds"] == 19800  # User added 2 GPU-hours for sparse/overlap; cumulative 5.5.
        ids = [j["job_id"] for j in ledger["jobs"] if j.get("job_id")]
        if ids:
            report = subprocess.check_output([
                "sacct", "-X", "-n", "-P", "-j", ",".join(ids),
                "--format=JobIDRaw,State,ElapsedRaw,AllocTRES"], text=True, timeout=20)
            reconcile(ledger, report)
            write_atomic(path, ledger)
        remaining = ledger["budget_gpu_seconds"] - used_or_reserved(ledger)
        print(json.dumps({"remaining_gpu_seconds": remaining, "ledger": ledger}), flush=True)
        if args.action == "status":
            return
        seconds = reservation(ledger, args.gpus, args.minutes)
        contexts = [int(c) for c in args.contexts.split(",")]
        if args.node and not re.fullmatch(r"paraai-n32-h-01-agent-[0-9]+", args.node):
            raise ValueError("Expected one explicit BLSC compute-node name")
        if args.exclude and any(not re.fullmatch(r"paraai-n32-h-01-agent-[0-9]+", n) for n in args.exclude.split(',')):
            raise ValueError("Expected explicit BLSC names in exclusions")
        assert contexts and all(64 < c <= 1010000 and c % 16 == 0 for c in contexts)
        assert 1 <= args.inputs <= 5 and args.repeats >= 1 and args.warmup >= 0
        # Created only after weights, isolated dependencies, and CPU imports pass.
        ready_path = root / "READY.json"
        ready = json.loads(ready_path.read_text())
        assert ready["weights_sha256_verified"] and ready["cpu_imports_passed"]
        assert ready.get('flash_ops_sm80_available'), 'A100 FlashAttention binary must be verified before another paid run'
        assert ready.get('activation_backend') == 'flashinfer.activation.silu_and_mul; CPU-built SM80'
        for library in ready['sm80_libraries'].values():
            assert hashlib.sha256(Path(library['library']).read_bytes()).hexdigest() == library['library_sha256']
        assert ready["model_revision"] == "e28526f7bb80e2a9c8af03b831a9af3812f18fba"
        assert Path(ready["python"]).is_file() and Path(ready["model"]).is_dir()
        for rel, digest in ready["runtime_files_sha256"].items():
            assert hashlib.sha256((root.parent / rel).read_bytes()).hexdigest() == digest, rel
        if not ready["runtime_files_sha256"]:
            raise ValueError("Runtime source manifest is required")
        (root / "logs").mkdir(exist_ok=True)
        job = {"submitted_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "requested_gpus": args.gpus, "time_limit_minutes": args.minutes,
               "reserved_gpu_seconds": seconds, "terminal": False,
               "status": "submission_pending", "contexts": contexts,
               "inputs": args.inputs, "repeats": args.repeats, "warmup": args.warmup}
        job['requested_node'] = args.node
        job['excluded_nodes'] = args.exclude.split(',') if args.exclude else []
        ledger["jobs"].append(job)
        write_atomic(path, ledger)
        env = os.environ.copy()
        env.update(AEGIS_ROOT=str(root.parent), AEGIS_PYTHON=ready["python"],
                   AEGIS_MODEL=ready["model"], TP=str(args.gpus),
                   CONTEXTS=args.contexts, INPUTS=str(args.inputs),
                   REPEATS=str(args.repeats), WARMUP=str(args.warmup))
        cmd = ["sbatch", "--parsable", "--partition=gpu", "--nodes=1", "--ntasks=1",
               f"--gpus-per-node={args.gpus}", f"--cpus-per-task={32 * args.gpus}",
               f"--time={args.minutes}", "--no-requeue", "--signal=B:TERM@15",
               "--job-name=aegis-qwen1m-budget", "--output=logs/%x-%j.log",
               str(root / "run_budgeted.sbatch")]
        if args.node:
            cmd.insert(-1, f"--nodelist={args.node}")
        if args.exclude:
            cmd.insert(-1, f"--exclude={args.exclude}")
        # Keep the reservation on any exception, including an ambiguous SSH loss.
        reply = subprocess.check_output(cmd, cwd=root, env=env, text=True).strip()
        job_id = reply.split(";")[0]
        if not job_id.isdigit():
            raise ValueError(f"Unexpected sbatch reply; reservation retained: {reply}")
        job.update(job_id=job_id, status="submitted")
        write_atomic(path, ledger)
        print(json.dumps(job), flush=True)


if __name__ == "__main__":
    main()
