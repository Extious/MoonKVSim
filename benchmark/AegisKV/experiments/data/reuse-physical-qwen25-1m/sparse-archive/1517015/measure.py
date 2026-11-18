#!/usr/bin/env python3
"""Physical paired KV recovery microbenchmark; run with torchrun under Slurm.

Native SGLang or vLLM DCA, BF16, batch 1, fixed known 64-token tail.
Backends are separate experimental configurations; do not merge their runs.
The timing endpoint is model-forward completion, before vocabulary projection.
This is a worker-level microbenchmark, not a serving/failure-detection benchmark.
"""
import argparse
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import time

os.environ.setdefault("VLLM_USE_V1", "0")
os.environ.setdefault("VLLM_ATTENTION_BACKEND", "DUAL_CHUNK_FLASH_ATTN")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

REVISION = "e28526f7bb80e2a9c8af03b831a9af3812f18fba"
MODEL = "Qwen/Qwen2.5-7B-Instruct-1M"
TEXTS = [
    "An agent reads a document, records its evidence, and sends a concise result to the coordinator. The coordinator waits for the required results before writing the final report.\n",
    "def sum_squares(values):\n    total = 0\n    for value in values:\n        total += value * value\n    return total\n# Review the code and explain its time and space complexity.\n",
    "A database stores ordered records with a key, timestamp, and value. A transaction reads a snapshot, updates two records, and commits only after both writes are durable.\n",
    "The telescope collected observations on five clear nights. The researcher calibrated each exposure, removed background noise, and compared the brightness measurements with a reference star.\n",
    "系统将工作流拆分为多个并行任务。每个任务保留输入和已经生成的状态。发生故障后，接管设备恢复历史状态，然后继续处理尚未完成的请求。\n",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--contexts", default="8192,16384,32768,65536,131072,262144,524288,786432,1010000")
    ap.add_argument("--inputs", type=int, default=5)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--chunk", type=int, default=8192)
    ap.add_argument("--backend", choices=["vllm", "sglang"], default="vllm")
    args = ap.parse_args()
    contexts = [int(x) for x in args.contexts.split(",")]
    assert 1 <= args.inputs <= len(TEXTS)
    assert args.repeats >= 1 and args.warmup in (0, 1)
    assert all(64 < n <= 1010000 and n % 16 == 0 for n in contexts)

    import torch
    import torch.distributed as dist
    if args.backend == "vllm":
        from transformers import AutoTokenizer
        import vllm
        from vllm.config import set_current_vllm_config
        from vllm.engine.arg_utils import EngineArgs
        from vllm.forward_context import set_forward_context
        from vllm.sequence import SequenceData, SequenceGroupMetadata
        from vllm.sampling_params import SamplingParams
        from vllm.worker.worker import Worker
    else:
        from sg_backend import SequenceData, SGLangAdapter

    rank = int(os.environ.get("RANK", "0"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    world = int(os.environ.get("WORLD_SIZE", "1"))
    torch.set_num_threads(4)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    def write(name, obj):
        if rank == 0:
            with (out / name).open("a") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            print(json.dumps(obj, ensure_ascii=False), flush=True)

    # Every length in one run uses the same TP group and native attention path.
    config_context = contextlib.nullcontext()
    if args.backend == "vllm":
        cfg = EngineArgs(
            model=args.model, tokenizer=args.model, dtype="bfloat16",
            tensor_parallel_size=world, pipeline_parallel_size=1,
            max_model_len=max(contexts), max_num_seqs=1,
            max_num_batched_tokens=args.chunk, enable_chunked_prefill=True,
            enable_prefix_caching=False, enforce_eager=True,
            block_size=16, swap_space=0, seed=17,
            disable_custom_all_reduce=True, trust_remote_code=False,
        ).create_engine_config()
        config_context = set_current_vllm_config(cfg)
    # Decode-mode correctness replays the last known token, staying inside C.

    with config_context, torch.inference_mode():
        torch.cuda.set_device(local_rank)
        props = torch.cuda.get_device_properties(local_rank)
        gpu_uuid = str(props.uuid)
        processes = subprocess.check_output([
            "nvidia-smi", "--query-compute-apps=gpu_uuid,pid,used_memory",
            "--format=csv,noheader,nounits"], text=True)
        foreign = [line for line in processes.splitlines()
                   if line.split(",")[0].strip() == gpu_uuid
                   and int(line.split(",")[1].strip()) != os.getpid()]
        (out / f"device-rank{rank}.json").write_text(json.dumps({
            "rank": rank, "uuid": gpu_uuid, "name": props.name,
            "visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "free_total_bytes_before_weights": list(torch.cuda.mem_get_info()),
            "foreign_compute_processes": foreign}, indent=2))
        if foreign:
            raise RuntimeError(f"Allocated GPU has another compute process: {foreign}")
        provenance = {}
        if args.backend == "sglang":
            runner = SGLangAdapter(args, contexts, rank, local_rank, world)
            caches, tokenizer, cfg = runner.caches, runner.tokenizer, runner.cfg
            framework = runner.framework
            provenance = runner.provenance
        else:
            worker = Worker(cfg, local_rank, rank, "env://", is_driver_worker=(rank == 0))
            worker.init_device()
            worker.load_model()
            runner = worker.model_runner
            cfg.cache_config.num_gpu_blocks = math.ceil((max(contexts) + 1) / 16)
            cfg.cache_config.num_cpu_blocks = 0
            worker._init_cache_engine()
            caches = worker.gpu_cache[0]
            assert runner.attn_backend.get_name() == "DUAL_CHUNK_FLASH_ATTN"
            impls = [layer.self_attn.attn.impl for layer in runner.model.model.layers]
            assert all(not x.sparse_attention_enabled for x in impls)
            tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
            framework = f"vllm {vllm.__version__}"
        assert all(x.dtype == torch.bfloat16 for x in caches)
        metadata = {
            "evidence": "physical_worker_microbenchmark", "model": MODEL,
            "revision": REVISION, "framework": framework,
            "torch": str(torch.__version__), "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(local_rank), "tp": world,
            "gpu_bytes": torch.cuda.get_device_properties(local_rank).total_memory,
            "host": platform.node(), "job_id": os.environ.get("SLURM_JOB_ID"),
            "dtype": "BF16", "batch": 1, "tail_tokens": 64,
            "attention": "native DualChunkFlashAttention; sparse acceleration disabled",
            "dca_config": cfg.model_config.hf_config.dual_chunk_attention_config,
            "contexts": contexts, "chunk_tokens": args.chunk,
            "inputs": args.inputs, "repeats": args.repeats, "warmup": args.warmup,
            "recompute_warmup": "untimed reference history and tail preparation; no duplicated full-history warmup",
            "input_kind": f"{args.inputs} fixed synthetic repeated text/code streams; not independent workloads",
            "endpoint": "all known-tail KV ready; excludes vocabulary projection",
            "dram": "complete pinned host KV, synchronous-before-compute H2D, no overlap",
            "pinned_host_allocation": "one maximum-history buffer per layer/rank, reused as prefix views across contexts",
            "hbm": "complete history resident on the recovery TP group",
            "recompute_schedule": "rebuild history with 8192-token chunks, then the same separate 64-token tail as reuse",
            "partition_equivalence": "ordinary fused-tail chunking is diagnostic only; not the timed recompute schedule",
            "timing": "synchronized perf_counter elapsed, maximum across TP ranks",
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "cache_shapes": [list(x.shape) for x in caches],
            "cache_dtypes": sorted({str(x.dtype) for x in caches}),
            **provenance,
        }
        if rank == 0:
            (out / "metadata.json").write_text(json.dumps(metadata, indent=2))

        def sync():
            torch.cuda.synchronize()
            dist.barrier()

        def reduce_max(value):
            x = torch.tensor(value, device="cuda", dtype=torch.float64)
            dist.all_reduce(x, op=dist.ReduceOp.MAX)
            return x.item()

        def forward(seq, count, blocks, request, prompt=True):
            if args.backend == "sglang":
                return runner.forward(seq, count, prompt)
            group = SequenceGroupMetadata(
                request_id=request, is_prompt=prompt, seq_data={0: seq},
                sampling_params=SamplingParams(temperature=0, max_tokens=1),
                block_tables={0: blocks}, token_chunk_size=count, do_sample=False,
            )
            mi = runner.prepare_model_input([group])
            assert len(mi.input_tokens) == count
            runner.attn_state.begin_forward(mi)
            with set_forward_context(mi.attn_metadata, cfg, 0):
                hidden = runner.model(input_ids=mi.input_tokens, positions=mi.input_positions)
            seq.update_num_computed_tokens(count)
            return hidden

        def run_prefix(seq, stop, blocks, request):
            hidden = None
            while seq.get_num_computed_tokens() < stop:
                n = min(args.chunk, stop - seq.get_num_computed_tokens())
                hidden = forward(seq, n, blocks, request)
            return hidden

        def reset_gpu():
            for x in caches:
                x.zero_()

        def compare(actual, reference):
            delta = (actual.float() - reference.float()).abs()
            err = reduce_max(delta.max().item())
            ok = reduce_max(float(not torch.allclose(actual, reference, rtol=0.01, atol=0.02))) == 0
            return ok, err

        # Reuse a single pinned allocation. Separate allocations at each length
        # can remain in PyTorch's host cache and exceed the Slurm RAM limit at
        # 1M even though the current history itself fits. Allocation is untimed.
        max_hblocks = (max(contexts) - 64) // 16
        host_pool = [torch.empty(x[:, :max_hblocks].shape, dtype=x.dtype,
                                 device="cpu", pin_memory=True) for x in caches]
        for context in contexts:
            history = context - 64
            hblocks = history // 16
            blocks = list(range(math.ceil((context + 1) / 16)))
            host = [x[:, :hblocks] for x in host_pool]
            assert all(x.is_contiguous() for x in host)
            moved_local = sum(x.numel() * x.element_size() for x in host)

            def restore():
                for gpu, cpu in zip(caches, host):
                    gpu[:, :hblocks].copy_(cpu, non_blocking=True)

            def tail_kv():
                return torch.stack([x[:, hblocks:hblocks + 4].clone() for x in caches])

            for input_id in range(args.inputs):
                base = tokenizer.encode(TEXTS[input_id], add_special_tokens=False)
                tokens = (base * math.ceil(context / len(base)))[:context]
                token_hash = hashlib.sha256(__import__("array").array("I", tokens).tobytes()).hexdigest()
                request = f"c{context}-i{input_id}"
                write("progress.jsonl", {"event": "preparing_history", "context": context, "input": input_id, "time": time.time()})
                reset_gpu()
                # Full C is retained in SequenceData even while only M is run:
                # native DCA's length scaling must be identical in all paths.
                seq = SequenceData.from_seqs(tokens)
                run_prefix(seq, history, blocks, request)
                for cpu, gpu in zip(host, caches):
                    cpu.copy_(gpu[:, :hblocks], non_blocking=True)
                torch.cuda.synchronize()
                ref_hidden = forward(seq, 64, blocks, request).clone()
                ref_kv = tail_kv()
                # The decode check replays the final known token in decode mode,
                # so the 1,010,000 context limit is never exceeded.
                ref_seq = SequenceData.from_seqs(tokens)
                ref_seq.update_num_computed_tokens(context - 1)
                ref_decode = forward(ref_seq, 1, blocks, request, prompt=False).clone()
                ref_logits = runner.model.compute_logits(ref_decode, None)
                ref_next = int(ref_logits.argmax(-1).item()) if rank == 0 else None

                # Diagnose the previously failing alternative partition once.
                # It is retained, not accepted as an equivalent execution.
                # The experiment below fixes the M/64 request boundary for all
                # paths, including reconstruction from an empty cache.
                if context == contexts[0] and input_id == 0:
                    reset_gpu()
                    diagnostic_seq = SequenceData.from_seqs(tokens)
                    ordinary = run_prefix(diagnostic_seq, context, blocks, request)[-64:]
                    ordinary_kv = tail_kv()
                    def metrics(actual, reference):
                        a, b = actual.float(), reference.float()
                        return {"max_abs": reduce_max((a-b).abs().max().item()),
                                "relative_l2": reduce_max(((a-b).norm()/b.norm()).item()),
                                "reference_max_abs": reduce_max(b.abs().max().item())}
                    write("partition-diagnostic.jsonl", {
                        "context_tokens": context, "timed": False,
                        "ordinary_vs_fixed_boundary_hidden": metrics(ordinary, ref_hidden),
                        "ordinary_vs_fixed_boundary_kv": metrics(ordinary_kv, ref_kv),
                        "per_layer_kv": [metrics(ordinary_kv[2*l:2*l+2], ref_kv[2*l:2*l+2])
                                         for l in range(len(caches)//2)],
                        "accepted_for_figure": False})
                    del ordinary, ordinary_kv
                full_checked = False
                for rep in range(-args.warmup, args.repeats):
                    paths = ["HBM", "DRAM", "Recompute"]
                    shift = (rep + args.warmup + input_id) % 3
                    paths = paths[shift:] + paths[:shift]
                    for path in paths:
                        if path == "Recompute" and rep < 0:
                            # Reference preparation already exercised the same
                            # history chunks and separate tail. Reuse it as the
                            # untimed warmup, not as a latency sample. The first
                            # timed empty-cache rebuild still independently
                            # checks all outputs against that reference.
                            write("trials.jsonl", {
                                "context_tokens": context, "history_tokens": history,
                                "tail_tokens": 64, "input_id": input_id,
                                "input_sha256": token_hash, "path": path,
                                "repetition": rep, "warmup": True,
                                "latency_ms": None, "transferred_bytes": 0,
                                "warmup_source": "untimed_reference_preparation",
                                "correctness": True, "status": "ok"})
                            continue
                        reset_gpu()
                        if path == "HBM":
                            restore()  # Outside timer: construct resident starting state.
                        seq = SequenceData.from_seqs(tokens)
                        sync()
                        started = time.perf_counter()
                        if path == "DRAM":
                            restore()
                        if path == "Recompute":
                            run_prefix(seq, history, blocks, request)
                            hidden = forward(seq, 64, blocks, request)
                        else:
                            seq.update_num_computed_tokens(history)
                            hidden = forward(seq, 64, blocks, request)
                        assert seq.get_num_computed_tokens() == context
                        torch.cuda.synchronize()
                        elapsed = (time.perf_counter() - started) * 1000
                        elapsed = reduce_max(elapsed)
                        hidden_ok, hidden_err = compare(hidden, ref_hidden)
                        kv_ok, kv_err = compare(tail_kv(), ref_kv)
                        if path == "Recompute" and not full_checked:
                            write("validation.jsonl", {
                                "context_tokens": context, "input_id": input_id,
                                "check": "empty_cache_fixed_boundary_recompute_vs_reuse",
                                "source_repetition": rep,
                                "hidden_max_abs": hidden_err, "tail_kv_max_abs": kv_err,
                                "rtol": 0.01, "atol": 0.02,
                                "correctness": hidden_ok and kv_ok})
                            full_checked = True
                        check_seq = SequenceData.from_seqs(tokens)
                        check_seq.update_num_computed_tokens(context - 1)
                        check_hidden = forward(check_seq, 1, blocks, request, prompt=False)
                        decode_ok, decode_err = compare(check_hidden, ref_decode)
                        logits = runner.model.compute_logits(check_hidden, None)
                        next_id = int(logits.argmax(-1).item()) if rank == 0 else None
                        next_bad = reduce_max(float(rank == 0 and next_id != ref_next))
                        okay = hidden_ok and kv_ok and decode_ok and not next_bad
                        row = {"context_tokens": context, "history_tokens": history,
                               "tail_tokens": 64, "input_id": input_id,
                               "input_sha256": token_hash, "path": path, "repetition": rep,
                               "warmup": rep < 0, "latency_ms": elapsed,
                               "transferred_bytes": moved_local * world if path == "DRAM" else 0,
                               "correctness": bool(okay), "hidden_max_abs": hidden_err,
                               "tail_kv_max_abs": kv_err, "decode_max_abs": decode_err,
                               "next_token_id": next_id, "reference_next_token_id": ref_next,
                               "status": "ok" if okay else "correctness_failed"}
                        write("trials.jsonl", row)
                        if not okay:
                            raise RuntimeError(f"Paired-state correctness failed: {row}")
                assert full_checked
                del ref_hidden, ref_kv, ref_decode, ref_logits, logits, hidden
            del host
            write("progress.jsonl", {"event": "context_complete", "context": context, "time": time.time()})
            # Commit only a fully paired, validated context. A later timeout or
            # OOM must not turn its partial trials into a plotted data point.
            sync()
            if rank == 0:
                (out / f"context-{context}-COMPLETE.json").write_text(json.dumps({
                    "context_tokens": context, "inputs": args.inputs,
                    "repeats": args.repeats, "warmup": args.warmup,
                    "completed_at": time.time()}))
        sync()
        if rank == 0:
            (out / "COMPLETE").write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n")


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
                json.dumps({"status": "failed", "type": type(exc).__name__,
                            "reason": str(exc), "traceback": traceback.format_exc()}, indent=2))
        raise
