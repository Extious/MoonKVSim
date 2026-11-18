#!/usr/bin/env python3
"""One-shot launcher: verified artifacts -> queue env -> pilot -> TP4 chain.

Only the pilot's successful Slurm exit releases the full matrix. A failed
correctness assertion exits nonzero, leaving the full job in dependency state.
This script never modifies the paper or marks partial data as measured.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-job", required=True)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = ap.parse_args()
    root = args.root
    state = {"env_job": args.env_job, "status": "waiting_for_weights_and_environment"}
    status_path = root / "launch-status.json"

    def save():
        state["updated_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        status_path.write_text(json.dumps(state, indent=2))

    if status_path.exists():
        old = json.loads(status_path.read_text())
        if old.get("pilot_job"):
            raise SystemExit("Already submitted; refusing duplicate GPU jobs.")
    save()
    while True:
        report = subprocess.check_output([
            "sacct", "-X", "-n", "-P", "-j", args.env_job,
            "--format=State,ExitCode"], text=True).strip().splitlines()
        env_state = report[0].split("|")[0] if report else "UNKNOWN"
        state.update(weights_ready=(root / "MODEL_COMPLETE").exists(), env_state=env_state)
        save()
        if any(env_state.startswith(s) for s in ["FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL"]):
            state["status"] = "environment_preflight_failed"
            save()
            raise SystemExit(f"Environment preflight did not pass: {env_state}")
        if state["weights_ready"]:
            break
        time.sleep(30)

    env = os.environ.copy()
    env.update(TP="1", CONTEXTS="8192,32768", INPUTS="1", REPEATS="3", WARMUP="1")
    pilot = subprocess.check_output([
        "sbatch", "--parsable", "--job-name=aegis-qwen1m-pilot",
        f"--dependency=afterok:{args.env_job}", "--kill-on-invalid-dep=yes",
        "--gres=gpu:1", "--cpus-per-task=4", "--mem=40G", "--time=00:45:00",
        str(root / "run_sglang.sbatch")], cwd=root, env=env, text=True).strip().split(";")[0]
    state.update(status="pilot_submitted", pilot_job=pilot)
    save()
    env.update(TP="4", CONTEXTS="8192,16384,32768,65536,131072,262144,524288,786432,1010000",
               INPUTS="5", REPEATS="5", WARMUP="1")
    full = subprocess.check_output([
        "sbatch", "--parsable", "--job-name=aegis-qwen1m-full",
        f"--dependency=afterok:{pilot}", "--kill-on-invalid-dep=yes",
        str(root / "run_sglang.sbatch")], cwd=root, env=env, text=True).strip().split(";")[0]
    state.update(status="pilot_and_full_matrix_submitted", full_job=full)
    save()
    print(json.dumps(state), flush=True)


if __name__ == "__main__":
    main()
