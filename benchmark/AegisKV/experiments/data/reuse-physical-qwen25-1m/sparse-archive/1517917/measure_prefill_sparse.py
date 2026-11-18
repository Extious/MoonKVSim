#!/usr/bin/env python3
"""Sparse Prefill matrix; reuse I/O completes before compute.

Optional shared-filesystem reuse adds direct file reads before serialized H2D.
Published three-path source remains frozen in sparse-archive/1517055.
"""
import argparse
import array
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import time

from measure import MODEL, REVISION, TEXTS
from measure_prefill_optimized import token_view
from layerwise_restore import LayerwiseRestore

PATHS = ("HBM", "DRAM_no_overlap")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--contexts", default="8192,65536,262144,1010000")
    ap.add_argument("--chunk", type=int, default=8192)
    ap.add_argument("--reuse-repeats", type=int, default=3)
    ap.add_argument("--full-repeats", type=int, default=1)
    ap.add_argument("--full-warmups", type=int, default=0)
    ap.add_argument("--sparse-head-group", type=int, default=2)
    ap.add_argument("--sharedfs-root")
    args = ap.parse_args()
    paths = PATHS + (("SharedFS_no_overlap",) if args.sharedfs_root else ())
    repeats = {p: (1 if p == "SharedFS_no_overlap" else args.reuse_repeats) for p in paths}
    contexts = [int(c) for c in args.contexts.split(",")]
    assert contexts == sorted(set(contexts)) and all(1 < c <= 1010000 for c in contexts)
    assert args.chunk == 8192 and args.reuse_repeats == 3
    assert 1 <= args.full_repeats <= 5 and 0 <= args.full_warmups <= 1
    import torch
    import torch.distributed as dist
    from sg_sparse_backend import SGLangAdapter
    from sg_backend import SequenceData
    rank, local_rank, world = [int(os.environ[k]) for k in ("RANK", "LOCAL_RANK", "WORLD_SIZE")]
    torch.cuda.set_device(local_rank)
    torch.set_num_threads(4)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    def emit(name, obj, all_ranks=False):
        if rank == 0 or all_ranks:
            with (out/name).open("a") as f:
                f.write(json.dumps(obj)+"\n")
            if rank == 0 and not name.startswith("timeline"):
                print(json.dumps(obj), flush=True)

    def sync():
        torch.cuda.synchronize()
        dist.barrier()

    def maximum(value):
        x = torch.tensor(value, dtype=torch.float64, device="cuda")
        dist.all_reduce(x, op=dist.ReduceOp.MAX)
        return x.item()

    def compare(a, b):
        finite = bool(torch.isfinite(a).all() and torch.isfinite(b).all())
        okay = finite and bool(torch.allclose(a, b, rtol=.01, atol=.02))
        err = maximum((a.float()-b.float()).abs().max().item())
        return maximum(float(not okay)) == 0, err

    with torch.inference_mode():
        runner = SGLangAdapter(args, contexts, rank, local_rank, world)
        torch.cuda.empty_cache()
        runner.run_operator_checks()
        caches = [token_view(c) for c in runner.caches]
        loader = LayerwiseRestore(runner, caches)
        storage_pool = []
        if args.sharedfs_root:
            from sharedfs_io import (ALIGNMENT, aligned_size, digest_views, direct_io,
                                     evict_own_file, residency)
            host_pool = []
            for cache in caches:
                token_bytes = math.prod(cache.shape[1:]) * cache.element_size()
                size = aligned_size((max(contexts)-1) * token_bytes)
                raw = torch.empty(size + ALIGNMENT, dtype=torch.uint8, pin_memory=True)
                shift = (-raw.data_ptr()) % ALIGNMENT
                raw = raw[shift:shift+size]
                storage_pool.append(raw)
                host_pool.append(raw.view(cache.dtype).reshape(-1, *cache.shape[1:]))
            storage_dir = Path(args.sharedfs_root)/os.environ["SLURM_JOB_ID"]
            storage_dir.mkdir(parents=True, exist_ok=True)
        else:
            host_pool = [torch.empty((max(contexts)-1, *c.shape[1:]), dtype=c.dtype, pin_memory=True)
                         for c in caches]
        verify_buffer = torch.empty_like(host_pool[0], pin_memory=True)
        meta = {
            "protocol": "sparse_prefill_kv_fill_one_token_v3_sharedfs" if args.sharedfs_root else "sparse_prefill_kv_fill_one_token_v2",
            "evidence": "physical_worker_microbenchmark", "model": MODEL, "revision": REVISION,
            "framework": runner.framework, "torch": str(torch.__version__), "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(local_rank), "host": platform.node(),
            "job_id": os.environ.get("SLURM_JOB_ID"), "tp": world, "dtype": "BF16", "batch": 1,
            "contexts": contexts, "new_tokens": 1, "chunk_tokens": args.chunk,
            "attention": "Qwen1M MInference vertical/slash + DCA, including one-token EXTEND; dense at/below 32K",
            "forward_mode": "EXTEND, including the final single new token",
            "endpoint": "synchronized model-body forward; all C-token KV resident; excludes lm_head",
            "history_tokens": "C-1, exact token slice including partial page",
            "paths": ["FullPrefill", *paths],
            "repeats_by_path": {"FullPrefill": args.full_repeats, **repeats},
            "inputs": 1, "input_kind": "fixed synthetic repeated text; no independent workflows",
            "hbm": "same sparse-generated prefix resident before timer; one final token",
            "dram_no_overlap": "all-layer pinned H2D completes before one-token forward",
            "dram_overlap": "layer-ordered H2D on dedicated stream, per-layer ready-event wait",
            "sharedfs": ("O_DIRECT file open/read/close into aligned pinned host memory, then all-layer H2D, then one-token forward; no I/O/compute overlap" if args.sharedfs_root else None),
            "sharedfs_cache": ("Linux file page residency checked before/after reads; remote service caches uncontrolled; not an SSD or cold-device measurement" if args.sharedfs_root else None),
            "sharedfs_samples": "one full read per length; no storage warmup, write/fsync and hash checks untimed",
            "sharedfs_io_sha256": hashlib.sha256((Path(__file__).parent/"sharedfs_io.py").read_bytes()).hexdigest() if args.sharedfs_root else None,
            "sharedfs_preflight": json.loads((out/"sharedfs-compute-preflight.json").read_text()) if args.sharedfs_root else None,
            "loading_scope": "all historical KV; no compression or selective loading",
            "timing": "synchronized wall time, maximum over TP ranks; CUDA event timeline on each rank",
            "warmup": ("operator checks and short forwards; "
                       + ("original all-head full-reference at 64K; " if 65536 in contexts else "no full-model all-head reference in this run; ")
                       + f"{args.full_warmups} full-length Prefill warmup per context; one HBM/DRAM warmup per context; no shared-filesystem read warmup"),
            "full_prefill_warmup_limit": ("one full-length warmup at every measured context" if args.full_warmups
                                           else "no duplicate full-length warmup at 256K or 1.01M"),
            "validation_limit": "paired sparse-state correctness is not dense equivalence or task-quality evaluation",
            "progress_logging": "one progress record per 131072 prefix tokens; included in wall timing",
            "allocator_config": os.environ.get("PYTORCH_CUDA_ALLOC_CONF"),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), **runner.provenance,
        }
        if rank == 0:
            (out/"metadata.json").write_text(json.dumps(meta, indent=2)+"\n")

        def clear():
            for c in caches:
                c.zero_()

        def prefix(seq, stop):
            while seq.computed < stop:
                runner.forward(seq, min(args.chunk, stop-seq.computed), True)
                if stop > 131072 and seq.computed % 131072 == 0:
                    emit("progress.jsonl", dict(event="prefix_progress", computed_tokens=seq.computed,
                                                target_tokens=stop, time=time.time()))

        summaries = []
        for context in contexts:
            history = context-1
            host = [h[:history] for h in host_pool]
            moved = sum(h.numel()*h.element_size() for h in host)
            assert moved == history * 28 * 2 * (4//world) * 128 * 2
            base = runner.tokenizer.encode(TEXTS[0], add_special_tokens=False)
            tokens = (base*math.ceil(context/len(base)))[:context]
            token_hash = hashlib.sha256(array.array("I", tokens).tobytes()).hexdigest()
            emit("progress.jsonl", dict(event="start_context", context=context, time=time.time()))
            clear()
            seq = SequenceData.from_seqs(tokens)
            runner.forward(seq, min(args.chunk, history), True)
            runner.forward(seq, 1, True)
            native_hidden = native_kv = None
            if context == 65536:
                clear()
                runner.use_reference(True)
                seq = SequenceData.from_seqs(tokens)
                prefix(seq, history)
                native_hidden = runner.forward(seq, 1, True).clone()
                native_kv = torch.stack([c[history:context].clone() for c in caches])
                runner.use_reference(False)
            full_trials = []
            initial_hidden = initial_kv = initial_next = None
            for full_rep in range(-args.full_warmups, args.full_repeats):
                clear()
                seq = SequenceData.from_seqs(tokens)
                sparse_before = runner.backend.aegis_sparse_invocations
                kernel_before = runner.sparse_kernel_calls
                sync()
                start = time.perf_counter()
                prefix(seq, history)
                ref_hidden = runner.forward(seq, 1, True)
                torch.cuda.synchronize()
                full_ms = maximum((time.perf_counter()-start)*1000)
                sparse_calls = runner.backend.aegis_sparse_invocations-sparse_before
                sparse_kernels = runner.sparse_kernel_calls-kernel_before
                assert (context <= 32768 and sparse_calls == 0) or (context > 32768 and sparse_calls > 0)
                assert (sparse_kernels > 0) == (context > 32768)
                ref_hidden = ref_hidden.clone()
                ref_kv = torch.stack([c[history:context].clone() for c in caches])
                ref_next = runner.compute_logits(ref_hidden, None).argmax(-1)
                assert bool(torch.isfinite(ref_hidden).all())
                if initial_hidden is None:
                    initial_hidden, initial_kv, initial_next = ref_hidden, ref_kv, ref_next
                else:
                    hidden_ok, hidden_err = compare(ref_hidden, initial_hidden)
                    kv_ok, kv_err = compare(ref_kv, initial_kv)
                    greedy_ok = maximum(float(not torch.equal(ref_next, initial_next))) == 0
                    assert hidden_ok and kv_ok and greedy_ok
                    emit("prefill-repeats-validation.jsonl", dict(context_tokens=context,
                         repetition=full_rep, correctness=True, hidden_max_abs=hidden_err,
                         new_kv_max_abs=kv_err, greedy_equal=greedy_ok))
                trial = dict(context_tokens=context, history_tokens=history, new_tokens=1,
                             input_sha256=token_hash, path="FullPrefill", repetition=full_rep,
                             warmup=full_rep < 0, latency_ms=full_ms, transferred_bytes=0,
                             sparse_prefix_layer_calls=sparse_calls, sparse_prefix_kernel_calls=sparse_kernels)
                full_trials.append(trial)
                emit("progress.jsonl", dict(event="full_prefill_trial_done", context=context,
                     repetition=full_rep, warmup=full_rep < 0, latency_ms=full_ms))
            del initial_hidden, initial_kv, initial_next
            if native_hidden is not None:
                nh_ok, nh_err = compare(ref_hidden, native_hidden)
                nk_ok, nk_err = compare(ref_kv, native_kv)
                record = dict(context_tokens=context, check="full_model_grouped_vs_all_heads_sparse",
                              hidden_max_abs=nh_err, new_kv_max_abs=nk_err, correctness=nh_ok and nk_ok)
                emit("sparse-model-validation.jsonl", record)
                assert record["correctness"], record
                del native_hidden, native_kv
            for cpu, gpu in zip(host, caches):
                cpu.copy_(gpu[:history], non_blocking=True)
            torch.cuda.synchronize()
            pending_full = full_trials[-1]
            emit("progress.jsonl", dict(event="full_prefill_done", context=context,
                                        latency_ms=full_ms, sparse_prefix_layer_calls=sparse_calls))
            times = {"FullPrefill": [t["latency_ms"] for t in full_trials if not t["warmup"]],
                     **{p: [] for p in paths}}
            storage_views = None
            if args.sharedfs_root:
                storage_views = []
                for raw, cpu in zip(storage_pool, host):
                    size = cpu.numel() * cpu.element_size()
                    end = aligned_size(size)
                    raw[size:end].zero_()
                    storage_views.append(memoryview(raw[:end].numpy()).cast("B"))
                checkpoint = storage_dir/f"context-{context}-rank-{rank}.bin"
                checkpoint_hash = digest_views(storage_views)
                emit("progress.jsonl", dict(event="sharedfs_write_start", context=context, time=time.time()))
                write_record = direct_io(checkpoint, storage_views, write=True)
                emit(f"storage-rank{rank}.jsonl", dict(event="checkpoint_written", context_tokens=context,
                     rank=rank, sha256=checkpoint_hash, logical_bytes=moved, **write_record), all_ranks=True)
                emit("progress.jsonl", dict(event="sharedfs_write_done", context=context, time=time.time()))

            def restore_untimed():
                for gpu, cpu in zip(caches, host):
                    gpu[:history].copy_(cpu, non_blocking=True)

            def check_history():
                # A complete bitwise check once per path/context, outside timing.
                okay = True
                buf = verify_buffer[:history]
                for gpu, cpu in zip(caches, host):
                    buf.copy_(gpu[:history], non_blocking=True)
                    torch.cuda.synchronize()
                    okay = okay and bool(torch.equal(buf, cpu))
                return maximum(float(not okay)) == 0

            for rep in range(-1, args.reuse_repeats):
                offset = rep % len(paths)
                for path in paths[offset:]+paths[:offset]:
                    if path == "SharedFS_no_overlap" and rep != 0:
                        continue
                    clear()
                    if path == "HBM":
                        restore_untimed()
                    seq = SequenceData.from_seqs(tokens)
                    seq.update_num_computed_tokens(history)
                    loader.prepare("DRAM_no_overlap" if path == "SharedFS_no_overlap" else path)
                    if path == "SharedFS_no_overlap":
                        for view in storage_pool:
                            view.zero_()
                        cache_before = evict_own_file(checkpoint)
                    new_kernel_before = runner.sparse_kernel_calls
                    sync()
                    start = time.perf_counter()
                    read_record = direct_io(checkpoint, storage_views) if path == "SharedFS_no_overlap" else None
                    loader.begin(host, history)
                    hidden = runner.forward(seq, 1, True)
                    torch.cuda.synchronize()
                    elapsed = maximum((time.perf_counter()-start)*1000)
                    new_sparse_kernels = runner.sparse_kernel_calls-new_kernel_before
                    assert (new_sparse_kernels > 0) == (context > 32768)
                    timeline = loader.finish()
                    timeline.update(context_tokens=context, repetition=rep, rank=rank, path=path)
                    if path == "SharedFS_no_overlap":
                        cache_after = residency(checkpoint)
                        checkpoint_ok = digest_views(storage_views) == checkpoint_hash
                        assert checkpoint_ok and cache_after["resident_pages"] == 0
                        record = dict(event="checkpoint_read", context_tokens=context, rank=rank,
                                      sha256=checkpoint_hash, sha256_equal=checkpoint_ok,
                                      client_cache_before=cache_before, client_cache_after=cache_after,
                                      logical_bytes=moved, **read_record)
                        emit(f"storage-rank{rank}.jsonl", record, all_ranks=True)
                        timeline["file_read_ms_before_cuda_origin"] = read_record["elapsed_ms"]
                    emit(f"timeline-rank{rank}.jsonl", timeline, all_ranks=True)
                    hidden_ok, hidden_err = compare(hidden, ref_hidden)
                    kv_ok, kv_err = compare(torch.stack([c[history:context] for c in caches]), ref_kv)
                    next_id = runner.compute_logits(hidden, None).argmax(-1)
                    next_ok = maximum(float(not torch.equal(next_id, ref_next))) == 0
                    hist_ok = check_history() if rep == 0 else None
                    okay = hidden_ok and kv_ok and next_ok and hist_ok is not False
                    row = {**pending_full, "path": path, "repetition": rep, "warmup": rep < 0,
                           "latency_ms": elapsed, "transferred_bytes": 0 if path == "HBM" else moved*world,
                           "sparse_prefix_layer_calls": 0,
                           "sparse_prefix_kernel_calls": 0,
                           "new_token_sparse_kernel_calls": new_sparse_kernels,
                           "hidden_max_abs": hidden_err, "new_token_kv_max_abs": kv_err,
                           "greedy_equal": next_ok, "history_bitwise_equal": hist_ok,
                           "correctness": okay, "status": "ok" if okay else "correctness_failed"}
                    if path == "SharedFS_no_overlap":
                        row.update(storage_read_bytes=sum(len(v) for v in storage_views)*world,
                                   storage_file_sha256_equal=True,
                                   client_cache_resident_pages_before=0, client_cache_resident_pages_after=0)
                    emit("trials.jsonl", row)
                    assert okay, row
                    if rep >= 0:
                        times[path].append(elapsed)
            for trial in full_trials:
                emit("trials.jsonl", {**trial, "correctness": True, "status": "ok",
                     "validation": "repeated Prefill outputs and matched sparse-prefix reuse states agree"})
            emit("validation.jsonl", dict(context_tokens=context, correctness=True,
                                          check="all measured paths agree; full historical KV checked"))
            for path, values in times.items():
                summaries.append(dict(context_tokens=context, history_tokens=history, new_tokens=1,
                                      path=path, latency_ms=statistics.median(values),
                                      trial_min_ms=min(values), trial_max_ms=max(values),
                                      timing_repeats_per_input=len(values), status="measured"))
            sync()
            if rank == 0:
                (out/f"context-{context}-COMPLETE.json").write_text(json.dumps({"context_tokens": context}))
                names = ["metadata.json", "trials.jsonl", "validation.jsonl"]
                names += [f"{prefix}-rank{i}.jsonl" for prefix in ("timeline", "sparse-operator") for i in range(world)]
                if args.sharedfs_root:
                    names += [f"storage-rank{i}.jsonl" for i in range(world)]
                    names.append("sharedfs-compute-preflight.json")
                if (out/"sparse-model-validation.jsonl").exists():
                    names.append("sparse-model-validation.jsonl")
                if (out/"prefill-repeats-validation.jsonl").exists():
                    names.append("prefill-repeats-validation.jsonl")
                hashes = {n: hashlib.sha256((out/n).read_bytes()).hexdigest() for n in names}
                (out/"measured.json").write_text(json.dumps({"evidence": meta["evidence"], "metadata": meta,
                    "source_sha256": hashes, "rows": summaries, "run_complete": context == contexts[-1],
                    "omitted_contexts": [c for c in contexts if c > context]}, indent=2)+"\n")
            if storage_views is not None:
                for view in storage_views:
                    view.release()
                checkpoint.unlink()
            del host, ref_hidden, ref_kv, hidden, seq
        if rank == 0:
            (out/"COMPLETE").write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import sys
        import traceback
        if "--output" in sys.argv:
            output = Path(sys.argv[sys.argv.index("--output")+1])
            output.mkdir(parents=True, exist_ok=True)
            (output/f"failure-rank{os.environ.get('RANK', '0')}.json").write_text(
                json.dumps({"error": str(exc), "traceback": traceback.format_exc()}, indent=2))
        raise
