#!/usr/bin/env python3
"""Isolated HBM read and pinned H2D payload bandwidth; no model inference.

Large BF16 buffers exceed A100's L2. HBM reads produce per-block checksums,
so loads cannot be eliminated. Both rates count input bytes exactly once.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time
import torch
import triton
import triton.language as tl


def main():
    @triton.jit
    def read_reduce(src, dst, N: tl.constexpr, BLOCK: tl.constexpr):
        block = tl.program_id(0)
        offset = block * BLOCK + tl.arange(0, BLOCK)
        values = tl.load(src + offset, offset < N, other=0, cache_modifier=".cg")
        tl.store(dst + block, tl.sum(values.to(tl.float32), axis=0))

    out = Path(os.environ["AEGIS_BANDWIDTH_OUT"])
    out.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    torch.cuda.set_device(0)
    props = torch.cuda.get_device_properties(0)
    processes = subprocess.check_output([
        "nvidia-smi", "--query-compute-apps=gpu_uuid,pid,used_memory",
        "--format=csv,noheader,nounits"], text=True)
    foreign = [line for line in processes.splitlines()
               if line.split(",")[0].strip() == str(props.uuid)
               and int(line.split(",")[1].strip()) != os.getpid()]
    assert not foreign, foreign
    metadata = {
        "evidence": "physical_isolated_bandwidth_microbenchmark",
        "host": platform.node(), "job_id": os.environ.get("SLURM_JOB_ID"),
        "gpu": props.name, "uuid": str(props.uuid), "gpu_count": 1,
        "torch": str(torch.__version__), "triton": triton.__version__,
        "cuda": torch.version.cuda, "dtype": "BF16",
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "sizes_bytes": [64 * 2**20, 256 * 2**20, 2**30],
        "warmup": 2, "timing_repeats": 9,
        "timing": "CUDA events; 5 HBM reads or 1 H2D copy per sample; median",
        "bandwidth_numerator": "payload input bytes once; GB = 1e9 bytes",
        "hbm": "streaming read with block FP32 checksum; not memcpy D2D",
        "h2d": "pinned host, nonblocking copy, synchronized events, no overlap",
        "scope": "single GPU; not model attention or TP2 aggregate bandwidth",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (out / "bandwidth-metadata.json").write_text(json.dumps(metadata, indent=2))
    rows = []
    for nbytes in metadata["sizes_bytes"]:
        n = nbytes // 2
        cpu = torch.ones(n, dtype=torch.bfloat16, pin_memory=True)
        gpu = torch.empty(n, dtype=torch.bfloat16, device="cuda")
        gpu.copy_(cpu, non_blocking=True)
        sums = torch.empty(triton.cdiv(n, 4096), dtype=torch.float32, device="cuda")
        def read():
            read_reduce[(triton.cdiv(n, 4096),)](gpu, sums, n, 4096, num_warps=4)
        for path, operation, inner in [("HBM_read", read, 5),
                                       ("pinned_H2D", lambda: gpu.copy_(cpu, non_blocking=True), 1)]:
            for _ in range(2):
                operation()
            torch.cuda.synchronize()
            values = []
            for _ in range(9):
                start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
                start.record()
                for _ in range(inner):
                    operation()
                end.record()
                end.synchronize()
                values.append(start.elapsed_time(end) / inner)
            read()
            torch.cuda.synchronize()
            assert bool(torch.all(sums == 4096).item()), "Payload/checksum validation failed"
            median_ms = statistics.median(values)
            row = {"path": path, "payload_bytes": nbytes, "latency_ms": median_ms,
                   "bandwidth_GB_s": nbytes / (median_ms * 1e6),
                   "bandwidth_GiB_s": nbytes / (median_ms / 1000 * 2**30),
                   "trials_ms": values, "correctness": True,
                   "checksum_output_bytes": sums.numel() * 4 if path == "HBM_read" else 0}
            rows.append(row)
            print(json.dumps(row), flush=True)
            (out / "bandwidth.json").write_text(json.dumps({"metadata": metadata, "rows": rows}, indent=2))
        del cpu, gpu, sums
    (out / "BANDWIDTH_COMPLETE").write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


if __name__ == "__main__":
    main()
