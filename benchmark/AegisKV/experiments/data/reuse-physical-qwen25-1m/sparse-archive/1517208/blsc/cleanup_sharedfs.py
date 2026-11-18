"""Remove only this experiment's generated KV files after the worker exits.

The parent batch invokes --batch-finalizer after waiting for its worker. An
external caller must verify terminal Slurm state before removing any file.
"""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--batch-finalizer", action="store_true")
    args = ap.parse_args()
    assert args.job_id.isdigit()
    root = Path(__file__).resolve().parent.parent
    if args.batch_finalizer:
        assert os.environ.get("SLURM_JOB_ID") == args.job_id
        state = "batch finalizer after worker wait"
    else:
        state = subprocess.check_output(["sacct", "-X", "-n", "-P", "-j", args.job_id,
                                         "--format=JobIDRaw,State"], text=True, timeout=15)
        states = [line.split("|")[1].split()[0].rstrip("+") for line in state.splitlines()
                  if line.split("|")[0] == args.job_id]
        assert states and all(s in {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL"}
                              for s in states), state
    target = root/"sharedfs-kv"/args.job_id
    removed = []
    if target.exists():
        assert not target.is_symlink() and target.resolve() == target
        for path in target.iterdir():
            st = path.lstat()
            assert re.fullmatch(r"context-[0-9]+-rank-[01]\.bin", path.name), path
            assert stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid() and st.st_nlink == 1
            removed.append(dict(path=str(path), bytes=st.st_size, inode=st.st_ino))
            path.unlink()
        target.rmdir()
    report = dict(job_id=args.job_id, state=state, removed=removed,
                  remaining_checkpoint_files=0, directory_exists=target.exists(),
                  time_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    out = root/"blsc/results"/args.job_id
    out.mkdir(parents=True, exist_ok=True)
    name = "sharedfs-batch-cleanup.json" if args.batch_finalizer else "sharedfs-terminal-cleanup.json"
    (out/name).write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
