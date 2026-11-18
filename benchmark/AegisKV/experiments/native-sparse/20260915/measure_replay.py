"""Measure the cost of replaying an unsealed tail on top of a restored history (MiniCPM4-8B, native sparse path).

A take-over engine that has the history KV of a request resident (restored from Peer HBM / DRAM) must still
recompute the tokens generated after the last sealed block.  This script measures exactly that step:

    1. full causal prefill of L random tokens into a fresh InfLLMv2Cache            (untimed here; Fig. 1 has it)
    2. forward of the next n tokens with that cache (chunked prefill over the cached history)   <- timed

Step 2 is repeated --repeats times on deep copies of the post-prefill cache so every repeat sees the same
state.  n = 1 is one decode step, n = 64 is a full unsealed block, n = 512 is the tail the earlier marginal
measurement (prefill(L+512) - prefill(L)) approximated.  Same bootstrap and kernels as the trace capture;
random ids because the selector picks a fixed top-k per query.  Batch 1, single GPU named in the JSON.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

import torch

PROJECT = Path('/home/comp/zhanzhao/MoonKVSim')
OUT = PROJECT / 'benchmark/AegisKV/experiments/native-sparse/20260915'
sys.path.insert(0, str(OUT))
sys.path.insert(0, str(PROJECT / 'benchmark/AegisKV/experiments/native-sparse/20260914'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--contexts', type=int, nargs='+', default=[8192, 16384, 32768])
    parser.add_argument('--tails', type=int, nargs='+', default=[1, 64, 512])
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--out-tag', default='', help='suffix for the output file, e.g. a100 (keeps runs on different GPUs apart)')
    args = parser.parse_args()
    assert torch.cuda.is_available()
    torch.manual_seed(20260915)
    import capture_minicpm4 as cm
    snapshot = cm.snapshot_dir()
    mod, _ = cm.bootstrap(snapshot)
    config = mod.MiniCPMConfig.from_pretrained(snapshot, local_files_only=True)
    config.sparse_config = dict(cm.SPARSE_CONFIG)
    model = mod.MiniCPMForCausalLM.from_pretrained(
        snapshot, config=config, torch_dtype=torch.bfloat16, device_map={'': 'cuda:0'},
        local_files_only=True, attn_implementation='flash_attention_2')
    model.eval()
    n_layers = len(model.model.layers)

    def new_cache():
        return mod.InfLLMv2Cache(config=model.config, num_hidden_layers=n_layers)

    def run(ids, cache, past_len):
        """Forward `ids` on top of `cache`; returns (logits, cache).  The checkpoint's forward replaces an
        empty cache with its own InfLLMv2Cache, so the returned cache must be used for the next call."""
        total = past_len + ids.shape[1]
        position_ids = torch.arange(past_len, total, device='cuda').unsqueeze(0)
        with torch.inference_mode():
            out = model(input_ids=ids, attention_mask=torch.ones(1, total, dtype=torch.long, device='cuda'),
                        position_ids=position_ids, past_key_values=cache, use_cache=True,
                        output_attentions=False, logits_to_keep=1)
        assert out.past_key_values.get_seq_length() == total, (out.past_key_values.get_seq_length(), total)
        return out.logits, out.past_key_values

    def timed(fn):
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        logits, cache = fn()
        torch.cuda.synchronize()
        assert torch.isfinite(logits).all()
        return time.perf_counter() - t0, cache

    g = torch.Generator(device='cpu').manual_seed(1)
    warm = torch.randint(100, config.vocab_size - 100, (1, 8704 + 64), generator=g).to('cuda')
    _, c = timed(lambda: run(warm[:, :8704], new_cache(), 0))
    timed(lambda: run(warm[:, 8704:], c, 8704))
    del c
    torch.cuda.empty_cache()
    rows = []
    skipped = []
    for L in args.contexts:
        ids = torch.randint(100, config.vocab_size - 100, (1, L + max(args.tails)), generator=g).to('cuda')
        torch.cuda.reset_peak_memory_stats()
        try:
            prefill_s, cache0 = timed(lambda: run(ids[:, :L], new_cache(), 0))
        except torch.OutOfMemoryError as e:                               # keep the shorter contexts; record the OOM
            skipped.append(dict(context=L, error=str(e).splitlines()[0][:200]))
            print('CTX', L, 'OOM', flush=True)
            del ids
            torch.cuda.empty_cache()
            continue
        for n in args.tails:
            samples = []
            for _ in range(args.repeats + 1):                          # first sample is the shape warm-up
                cache = copy.deepcopy(cache0)
                t, cache = timed(lambda: run(ids[:, L:L + n], cache, L))
                samples.append(t)
                del cache
            samples = samples[1:]
            row = dict(context=L, tail=n, prefill_s=prefill_s, replay_s=samples, replay_median_s=statistics.median(samples),
                       replay_per_layer_ms=statistics.median(samples) / n_layers * 1e3,
                       peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated())
            rows.append(row)
            print('CTX', L, 'tail', n, 'replay', round(row['replay_median_s'] * 1e3, 2), 'ms  per layer',
                  round(row['replay_per_layer_ms'], 3), 'ms  peak GiB', round(row['peak_cuda_allocated_bytes'] / 2**30, 2), flush=True)
        del cache0, ids
        torch.cuda.empty_cache()
    meta = dict(model='openbmb/MiniCPM4-8B', revision=snapshot.name, layers=n_layers,
                kv_heads=config.num_key_value_heads, head_dim=config.hidden_size // config.num_attention_heads,
                kv_bytes_per_token_per_layer=2 * config.num_key_value_heads * (config.hidden_size // config.num_attention_heads) * 2,
                sparse_config=dict(cm.SPARSE_CONFIG), vocab=config.vocab_size)
    result = dict(meta=meta, gpu=torch.cuda.get_device_name(0), host=platform.node(),
                  slurm_job_id=os.environ.get('SLURM_JOB_ID'), torch=torch.__version__, cuda=torch.version.cuda,
                  protocol='batch 1; prefill L random ids into an InfLLMv2Cache; then forward the next n ids with a deep copy of '
                           'that cache (chunked prefill over the cached history, native sparse path); median of repeats after '
                           'one shape warm-up; replay_per_layer_ms = median / layers',
                  rows=rows, skipped_out_of_memory=skipped)
    path = OUT / ('replay-latency-minicpm4-8b' + (f'-{args.out_tag}' if args.out_tag else '') + '.json')
    path.write_text(json.dumps(result, indent=2) + '\n')
    print('WROTE', path, flush=True)


if __name__ == '__main__':
    main()
