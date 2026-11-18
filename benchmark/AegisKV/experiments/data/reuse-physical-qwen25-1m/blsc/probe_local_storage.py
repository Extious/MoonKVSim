"""Read-only storage discovery inside an authorized, short Slurm allocation.

No model imports, GPU operations, benchmark writes, or filesystem changes.
The only output file is an audit in this experiment's results directory.
"""
import json
import os
from pathlib import Path
import platform
import subprocess
import time


def command(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=6)
        return dict(argv=argv, returncode=result.returncode,
                    stdout=result.stdout, stderr=result.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return dict(argv=argv, error=str(exc))


def main():
    root = Path(__file__).resolve().parent.parent
    out = root / "blsc/results" / os.environ["SLURM_JOB_ID"]
    out.mkdir(parents=True, exist_ok=True)
    records = [command(argv) for argv in [
        ["lsblk", "-b", "-J", "-o", "NAME,KNAME,PKNAME,TYPE,SIZE,ROTA,MODEL,TRAN,MOUNTPOINT"],
        ["findmnt", "-J", "-t", "ext4,xfs,btrfs,nfs,nfs4,tmpfs", "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"],
        ["df", "-h", "/tmp", "/var/tmp", str(root)],
    ]]
    candidates = {}
    for p in ["/tmp", "/var/tmp", "/scratch", "/local", "/data", "/mnt", "/ssd", "/nvme"]:
        path = Path(p)
        if path.exists():
            st = os.statvfs(path)
            candidates[p] = dict(writable=os.access(path, os.W_OK),
                                 free_bytes=st.f_bavail * st.f_frsize,
                                 mount=command(["findmnt", "-J", "-T", p, "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"]))
    devices = {}
    for disk in Path("/sys/block").iterdir():
        values = {}
        for name in ["device/model", "device/vendor", "queue/rotational", "queue/logical_block_size", "size"]:
            try:
                values[name] = (disk / name).read_text().strip()
            except OSError:
                pass
        devices[disk.name] = values
    report = dict(time_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  host=platform.node(), job_id=os.environ["SLURM_JOB_ID"],
                  gpu_operations=False, storage_test_writes=False,
                  environment={k: v for k, v in os.environ.items()
                               if k in ("TMPDIR", "SLURM_TMPDIR", "LOCAL_SCRATCH", "SCRATCH")},
                  commands=records, candidates=candidates, block_devices=devices)
    (out / "storage-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
