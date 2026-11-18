#!/usr/bin/env python3
"""KV-fill latency: empty-cache Prefill versus cached-prefix 1-token EXTEND.

Uses real weights and the unchanged SGLang adapter. No failure injection and no
64-token tail. A single timed empty-cache Prefill supplies the reference state;
HBM/DRAM reuse are checked against it. Historical recovery data stay untouched.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time

from measure import MODEL, REVISION, TEXTS


def token_view(cache):
    """Flatten physical pages without losing the partial last history page."""
    assert cache.is_contiguous() and cache.shape[0] == 1
    return cache.view(-1, *cache.shape[-2:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--contexts", default="8192,65536,262144,1010000")
    ap.add_argument("--chunk", type=int, default=8192)
    ap.add_argument("--reuse-repeats", type=int, default=3)
    args = ap.parse_args()
    contexts = [int(n) for n in args.contexts.split(",")]
    assert contexts == sorted(set(contexts)) and all(1 < c <= 1010000 for c in contexts)
    assert args.chunk == 8192 and args.reuse_repeats >= 1
    import torch
    import torch.distributed as dist
    from sg_backend import SequenceData, SGLangAdapter
    rank = int(os.environ["RANK"])
    local_rank = int(os.environ["LOCAL_RANK"])
    world = int(os.environ["WORLD_SIZE"])
    torch.cuda.set_device(local_rank)
    torch.set_num_threads(4)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    props = torch.cuda.get_device_properties(local_rank)
    processes = subprocess.check_output([
        "nvidia-smi", "--query-compute-apps=gpu_uuid,pid,used_memory",
        "--format=csv,noheader,nounits"], text=True)
    foreign = [line for line in processes.splitlines()
               if line.split(",")[0].strip() == str(props.uuid)
               and int(line.split(",")[1].strip()) != os.getpid()]
    assert not foreign, foreign

    def write(name, obj):
        if rank == 0:
            with (out / name).open("a") as f:
                f.write(json.dumps(obj) + "\n")
            print(json.dumps(obj), flush=True)

    with torch.inference_mode():
        runner = SGLangAdapter(args, contexts, rank, local_rank, world)
        caches = [token_view(c) for c in runner.caches]
        host_pool = [torch.empty((max(contexts)-1, *c.shape[1:]),
                                dtype=c.dtype, pin_memory=True) for c in caches]
        meta = {
            "protocol": "prefill_kv_fill_one_token_v1",
            "evidence": "physical_worker_microbenchmark", "model": MODEL,
            "revision": REVISION, "framework": runner.framework,
            "torch": str(torch.__version__), "cuda": torch.version.cuda,
            "gpu": props.name, "tp": world, "host": platform.node(),
            "job_id": os.environ.get("SLURM_JOB_ID"), "dtype": "BF16", "batch": 1,
            "contexts": contexts, "new_tokens": 1, "chunk_tokens": args.chunk,
            "dca_config": runner.cfg.model_config.hf_config.dual_chunk_attention_config,
            "attention": "native DCA, sparse acceleration disabled; unchanged adapter",
            "forward_mode": "EXTEND, including the single new token",
            "endpoint": "synchronized model-body Prefill completion; all C token KV populated; excludes lm_head",
            "endpoint_limit": "Includes final layer attention/MLP; not an instrumented last-KV-write timestamp",
            "history_tokens": "C-1; exact token slice, including partial page",
            "hbm": "M=C-1 KV resident before timing; Prefill one new token",
            "dram": "exactly M token KV copied from pinned DRAM before same one-token Prefill; no overlap",
            "recompute_schedule": "empty-cache Prefill of M in <=8192-token chunks, followed by one-token EXTEND",
            "repeats_by_path": {"HBM": args.reuse_repeats, "DRAM": args.reuse_repeats, "Recompute": 1},
            "inputs": 1, "input_kind": "fixed synthetic repeated text; not independent workflows",
            "warmup": "untimed short Prefill/EXTEND kernel audit; DECODE audited only after full context KV exists; one HBM and DRAM warmup per context",
            "recompute_warmup_limit": "One timed full Prefill per context; no duplicated full-context warmup. First shape-specific setup is included.",
            "timing": "synchronized perf_counter; maximum across TP ranks",
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            **runner.provenance,
        }
        if rank == 0:
            (out / "metadata.json").write_text(json.dumps(meta, indent=2))

        def sync():
            torch.cuda.synchronize()
            dist.barrier()

        def maximum(value):
            x = torch.tensor(value, dtype=torch.float64, device="cuda")
            dist.all_reduce(x, op=dist.ReduceOp.MAX)
            return x.item()

        def reset():
            for c in caches:
                c.zero_()

        def prefix(seq, stop):
            while seq.computed < stop:
                runner.forward(seq, min(args.chunk, stop-seq.computed), True)

        def compare(a, b):
            error = maximum((a.float()-b.float()).abs().max().item())
            good = maximum(float(not torch.allclose(a, b, rtol=.01, atol=.02))) == 0
            return good, error

        summaries = []
        for context in contexts:
            history = context - 1
            host = [h[:history] for h in host_pool]
            moved = sum(h.numel() * h.element_size() for h in host)
            assert all(h.is_contiguous() for h in host)
            assert moved == history * 28 * 2 * (4 // world) * 128 * 2
            base = runner.tokenizer.encode(TEXTS[0], add_special_tokens=False)
            tokens = (base * math.ceil(context / len(base)))[:context]
            token_hash = hashlib.sha256(__import__("array").array("I", tokens).tobytes()).hexdigest()
            write("progress.jsonl", {"event": "start_context", "context": context, "time": time.time()})
            # Warm the timed EXTEND modes. Keep full C for DCA length scaling.
            # Native DECODE metadata requires the full C-token page table;
            # audit it below only after all C tokens' KV has been populated.
            reset()
            warm_seq = SequenceData.from_seqs(tokens)
            runner.forward(warm_seq, min(args.chunk, history), True)
            runner.forward(warm_seq, 1, True)

            reset()
            seq = SequenceData.from_seqs(tokens)
            sync()
            start = time.perf_counter()
            prefix(seq, history)
            ref_hidden = runner.forward(seq, 1, True)
            torch.cuda.synchronize()
            full_ms = maximum((time.perf_counter()-start)*1000)
            ref_hidden = ref_hidden.clone()
            ref_kv = torch.stack([c[history:context].clone() for c in caches])
            # D2H backup creation is setup, excluded from all three latencies.
            for cpu, gpu in zip(host, caches):
                cpu.copy_(gpu[:history], non_blocking=True)
            torch.cuda.synchronize()
            seq.computed = history
            ref_decode = runner.forward(seq, 1, False).clone()
            logits = runner.compute_logits(ref_decode, None)
            ref_next = int(logits.argmax(-1).item()) if rank == 0 else None
            times = {"Recompute": [full_ms], "HBM": [], "DRAM": []}
            pending_full = {"context_tokens": context, "history_tokens": history, "new_tokens": 1,
                            "path": "Recompute", "repetition": 0, "latency_ms": full_ms,
                            "input_sha256": token_hash, "transferred_bytes": 0}

            def restore():
                for gpu, cpu in zip(caches, host):
                    gpu[:history].copy_(cpu, non_blocking=True)

            for rep in range(-1, args.reuse_repeats):
                for path in (["HBM", "DRAM"] if rep % 2 else ["DRAM", "HBM"]):
                    reset()
                    if path == "HBM":
                        restore()
                    seq = SequenceData.from_seqs(tokens)
                    sync()
                    start = time.perf_counter()
                    if path == "DRAM":
                        restore()
                        torch.cuda.synchronize()
                    seq.update_num_computed_tokens(history)
                    hidden = runner.forward(seq, 1, True)
                    torch.cuda.synchronize()
                    elapsed = maximum((time.perf_counter()-start)*1000)
                    hidden_ok, hidden_err = compare(hidden, ref_hidden)
                    kv_ok, kv_err = compare(torch.stack([c[history:context] for c in caches]), ref_kv)
                    seq.computed = history
                    decode = runner.forward(seq, 1, False)
                    decode_ok, decode_err = compare(decode, ref_decode)
                    logits = runner.compute_logits(decode, None)
                    next_id = int(logits.argmax(-1).item()) if rank == 0 else None
                    next_ok = maximum(float(rank == 0 and next_id != ref_next)) == 0
                    okay = hidden_ok and kv_ok and decode_ok and next_ok
                    row = {**pending_full, "path": path, "repetition": rep,
                           "latency_ms": elapsed, "warmup": rep < 0,
                           "transferred_bytes": moved * world if path == "DRAM" else 0,
                           "hidden_max_abs": hidden_err, "new_token_kv_max_abs": kv_err,
                           "decode_max_abs": decode_err, "correctness": okay,
                           "status": "ok" if okay else "correctness_failed"}
                    write("trials.jsonl", row)
                    assert okay, row
                    if rep >= 0:
                        times[path].append(elapsed)
            write("trials.jsonl", {**pending_full, "warmup": False, "correctness": True,
                                   "validation": "reference agrees with all cached-prefix reuse trials", "status": "ok"})
            write("validation.jsonl", {"context_tokens": context, "correctness": True,
                                       "check": "one-token EXTEND HBM/DRAM versus empty-cache Prefill reference"})
            for path, values in times.items():
                summaries.append({"context_tokens": context, "history_tokens": history,
                                  "new_tokens": 1, "path": path, "latency_ms": statistics.median(values),
                                  "trial_min_ms": min(values), "trial_max_ms": max(values),
                                  "timing_repeats_per_input": len(values), "status": "measured"})
            sync()
            if rank == 0:
                (out / f"context-{context}-COMPLETE.json").write_text(json.dumps({"context_tokens": context}))
                hashes = {n: hashlib.sha256((out/n).read_bytes()).hexdigest()
                          for n in ["metadata.json", "trials.jsonl", "validation.jsonl"]}
                (out / "measured.json").write_text(json.dumps({"evidence": meta["evidence"],
                    "metadata": meta, "source_sha256": hashes, "rows": summaries,
                    "run_complete": context == contexts[-1],
                    "omitted_contexts": [c for c in contexts if c > context]}, indent=2))
            del host, ref_kv, ref_hidden, ref_decode, logits, hidden, decode, seq
        if rank == 0:
            (out / "COMPLETE").write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import sys
        import traceback
        if "--output" in sys.argv:
            output = Path(sys.argv[sys.argv.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / f"failure-rank{os.environ.get('RANK', '0')}.json").write_text(
                json.dumps({"error": str(exc), "traceback": traceback.format_exc()}, indent=2))
        raise
