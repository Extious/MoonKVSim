#!/usr/bin/env python3
"""Bounded Qwen3-8B / CUDA DMA microbenchmark on an exclusive Slurm allocation.

This measures foreground forwards, memory occupancy and copy/free completion.
It is not the three-system serving benchmark and does not emulate a GPU fault.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import random
import socket
import subprocess
import threading
import time


def main():
    import torch
    import transformers
    from transformers import AutoModelForCausalLM

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--repeats", type=int, default=5)
    args = p.parse_args()
    if not os.environ.get("SLURM_JOB_ID") or torch.cuda.device_count() != 2:
        raise RuntimeError("requires a two-GPU Slurm allocation")
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(8)
    torch.manual_seed(20260908)
    model = AutoModelForCausalLM.from_pretrained(str(args.model), local_files_only=True,
        dtype=torch.bfloat16, attn_implementation="sdpa").to("cuda:0").eval()
    can_peer = bool(torch.cuda.can_device_access_peer(0, 1))
    meta = {"schema": "aegiskv.native_interference_microbenchmark.v1",
        "job_id": os.environ["SLURM_JOB_ID"], "hostname": socket.gethostname(),
        "devices": [str(torch.cuda.get_device_properties(i)) for i in (0, 1)],
        "torch": torch.__version__, "transformers": transformers.__version__,
        "cuda": torch.version.cuda, "direct_peer_supported": can_peer,
        "model_snapshot": str(args.model), "model_config_sha256": hashlib.sha256((args.model / "config.json").read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "precision": "BF16", "attention": "PyTorch SDPA", "repeats_per_condition": args.repeats,
        "independent_allocations": 1, "random_seed": 20260908,
        "scope": "real_model_forward_and_DMA_microbenchmark_not_native_AegisKV_end_to_end"}
    (args.output / "manifest.json").write_text(json.dumps(meta, indent=2) + "\n")
    (args.output / "topology.txt").write_text(subprocess.check_output(["nvidia-smi", "topo", "-m"], text=True))
    # Fixed 256 MiB buffers avoid allocating unbounded work in the copy thread.
    nbytes = 256 * 1024**2
    source0 = torch.zeros(nbytes, device="cuda:0", dtype=torch.uint8)
    source1 = torch.zeros(nbytes, device="cuda:1", dtype=torch.uint8)
    target0 = torch.empty_like(source0)
    target1 = torch.empty_like(source1)
    host = torch.empty(nbytes, pin_memory=True, dtype=torch.uint8)
    copy_stream = torch.cuda.Stream(device=0)
    ready, stop = threading.Event(), threading.Event()
    copies = []
    errors = []

    def copier(mode):
        try:
            torch.cuda.set_device(0)
            with torch.cuda.stream(copy_stream):
                ready.set()
                while not stop.is_set():
                    start_cpu = time.thread_time_ns()
                    start = time.perf_counter_ns()
                    if mode == "peer_in":
                        target0.copy_(source1, non_blocking=True)
                    elif mode == "peer_out":
                        target1.copy_(source0, non_blocking=True)
                    elif mode == "dram_put":
                        host.copy_(source0, non_blocking=True)
                    else:
                        raise ValueError(mode)
                    copy_stream.synchronize()
                    copies.append({"mode": mode, "bytes": nbytes,
                        "wall_ns": time.perf_counter_ns() - start,
                        "cpu_ns": time.thread_time_ns() - start_cpu})
        except BaseException as exc:
            errors.append(repr(exc)); ready.set()

    rows = []
    # Interleave modes within every block. Repeat index is a within-allocation
    # measurement block, not an independent machine or a serving-system run.
    conditions = [(batch, tokens, gib, mode) for batch in (1, 4) for tokens in (512, 2048, 4096)
        for gib in (0, 8, 16) for mode in (("none", "dram_put", "peer_in", "peer_out") if can_peer else ("none", "dram_put"))]
    rng = random.Random(20260908)
    with (args.output / "samples.jsonl").open("w") as out, torch.inference_mode():
        for repeat in range(args.repeats):
            order = conditions.copy(); rng.shuffle(order)
            for batch, tokens, gib, mode in order:
                condition = {"repeat": repeat, "batch": batch, "prompt_tokens": tokens,
                    "backup_occupancy_gib": gib, "mode": mode}
                reserve = inputs = result = None
                worker = None
                try:
                    reserve = torch.empty(gib * 1024**3, dtype=torch.uint8, device="cuda:0")
                    reserve.fill_(0)
                    inputs = torch.randint(100, 30000, (batch, tokens), device="cuda:0")
                    for _ in range(2):
                        result = model(inputs, use_cache=False, logits_to_keep=1)
                    del result; result = None
                    torch.cuda.synchronize(0)
                    stop.clear(); ready.clear()
                    copy_start = len(copies)
                    if mode != "none":
                        worker = threading.Thread(target=copier, args=(mode,))
                        worker.start(); ready.wait(5)
                    before_mem = torch.cuda.memory_allocated(0)
                    start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
                    cpu0, wall0 = time.process_time_ns(), time.perf_counter_ns()
                    start.record()
                    result = model(inputs, use_cache=False, logits_to_keep=1)
                    end.record(); end.synchronize()
                    elapsed = time.perf_counter_ns() - wall0
                    cpu = time.process_time_ns() - cpu0
                    stop.set()
                    if worker:
                        worker.join(30)
                        if worker.is_alive():
                            raise RuntimeError("DMA thread failed to acknowledge stop")
                    if errors:
                        raise RuntimeError(errors[-1])
                    measured = copies[copy_start:]
                    row = {**condition, "status": "PASS", "forward_gpu_ms": start.elapsed_time(end),
                        "forward_wall_ns": elapsed, "process_cpu_ns": cpu, "allocated_bytes": before_mem,
                        "copy_count": len(measured), "copy_samples": measured}
                except torch.OutOfMemoryError:
                    stop.set()
                    if worker:
                        worker.join(30)
                    row = {**condition, "status": "OOM"}
                finally:
                    stop.set()
                    del reserve, inputs, result
                    gc.collect(); torch.cuda.empty_cache()
                rows.append(row)
                out.write(json.dumps(row) + "\n"); out.flush()
                print(json.dumps({k: v for k, v in row.items() if k != "copy_samples"}), flush=True)
    # Real allocation/free completion, including synchronizing the copy stream.
    free_rows = []
    for gib in (1, 4, 8):
        for repeat in range(20):
            x = torch.empty(gib * 1024**3, device="cuda:0", dtype=torch.uint8)
            with torch.cuda.stream(copy_stream):
                x.fill_(1)
            at = time.perf_counter_ns()
            copy_stream.synchronize()
            ack = time.perf_counter_ns()
            del x
            torch.cuda.empty_cache()
            torch.cuda.synchronize(0)
            free_rows.append({"gib": gib, "repeat": repeat, "fence_ns": ack - at,
                "allocator_free_ns": time.perf_counter_ns() - ack})
    (args.output / "reclaim.json").write_text(json.dumps(free_rows, indent=2) + "\n")
    meta["status"] = "PASS"
    meta["sample_count"] = len(rows)
    meta["oom_count"] = sum(r["status"] == "OOM" for r in rows)
    meta["samples_sha256"] = hashlib.sha256((args.output / "samples.jsonl").read_bytes()).hexdigest()
    (args.output / "manifest.json").write_text(json.dumps(meta, indent=2) + "\n")


if __name__ == "__main__":
    main()
