"""Measure native sparse full-prefill latency with a common retained-KV contract.

Figure 4 (recompute cost) protocol v2: BF16, batch 1, single GPU, official checkpoint sparse kernels,
empty cache at the beginning of every forward, complete history KV retained until
CUDA synchronization. Warm each shape and report all repetitions, not estimates.
Random-token inputs are a reproducible microbenchmark, NOT content-independent or
agent-workload evidence. The optional difference t(L+tail)-t(L) is not cached replay.
Legacy JSON files are preserved; every new run requires a unique --out-tag.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import torch

PROJECT = Path('/home/comp/zhanzhao/MoonKVSim')
OUT = PROJECT / 'benchmark/AegisKV/experiments/native-sparse/20260915'
MODEL_ROOT = PROJECT / 'benchmark/AegisKV/experiments/native-sparse/runtime-20260914'
sys.path.insert(0, str(OUT))
sys.path.insert(0, str(PROJECT / 'benchmark/AegisKV/experiments/native-sparse/20260914'))
NOSA = {
    'nosa-1b': ('NOSA-1B', '7bdc33fbc1bc80b76b29689ba35ff6a7991b7dee'),
    'nosa-3b': ('NOSA-3B', 'c5a4d505d5811f7555d786a031a4623787da7fb0'),
    'nosa-8b': ('NOSA-8B', '6da5609664fa64ea55125a32e7cb70f541d97ea9'),
}


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def validate_loading(loading):
    assert not any(loading.get(k) for k in ('missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs')), loading


def load_minicpm4():
    import capture_minicpm4 as cm
    snapshot = cm.snapshot_dir()
    mod, kernel = cm.bootstrap(snapshot)
    config = mod.MiniCPMConfig.from_pretrained(snapshot, local_files_only=True)
    config.sparse_config = dict(cm.SPARSE_CONFIG)
    model, loading = mod.MiniCPMForCausalLM.from_pretrained(
        snapshot, config=config, torch_dtype=torch.bfloat16, device_map={'': 'cuda:0'},
        local_files_only=True, attn_implementation='flash_attention_2', output_loading_info=True)
    validate_loading(loading)
    model.eval()

    def forward(ids):
        cache = mod.InfLLMv2Cache(config=model.config, num_hidden_layers=len(model.model.layers))
        with torch.inference_mode():
            return model(input_ids=ids, attention_mask=torch.ones_like(ids), past_key_values=cache,
                         use_cache=True, output_attentions=False, logits_to_keep=1)

    meta = model_metadata(model, mod, snapshot, 'openbmb/MiniCPM4-8B', snapshot.name,
                          cm.SPARSE_CONFIG, kernel, loading)
    return forward, meta, mod


def load_nosa(name):
    import capture_native as cn
    from transformers import LlamaConfig
    model_name, revision = NOSA[name]
    snapshot = MODEL_ROOT / model_name
    # Reuse only the import bootstrap. Each process loads its own unmodified pinned checkpoint code.
    cn.CHECKPOINT = snapshot
    mod, _, kernel, _ = cn.bootstrap()
    config = LlamaConfig.from_pretrained(snapshot, local_files_only=True)
    config._attn_implementation = 'sdpa'
    model, loading = mod.SparseLlamaForCausalLM.from_pretrained(
        snapshot, config=config, torch_dtype=torch.bfloat16, device_map={'': 'cuda:0'},
        local_files_only=True, attn_implementation='sdpa', output_loading_info=True)
    validate_loading(loading)
    model.eval()
    for layer in model.model.layers:
        assert isinstance(layer.self_attn, mod.LlamaSdpaAttention)
        assert layer.self_attn.dense_len == 0 and layer.self_attn.topk == 64
    assert all(float(layer.self_attn.delta.weight.float().norm()) > 0 for layer in model.model.layers)

    def forward(ids):
        from transformers.cache_utils import DynamicCache
        # Empty explicit cache avoids legacy tuple conversion; retained K/V is checked outside timing.
        cache = DynamicCache()
        with torch.inference_mode():
            return model(input_ids=ids, attention_mask=torch.ones_like(ids), past_key_values=cache,
                         use_cache=True, output_attentions=False, num_logits_to_keep=1)

    attn = model.model.layers[0].self_attn
    sparse = {k: getattr(attn, k) for k in ('kernel_size', 'kernel_stride', 'block_size', 'window_size',
                                          'local_blocks', 'init_blocks', 'topk', 'dense_len')}
    meta = model_metadata(model, mod, snapshot, 'openbmb/' + model_name, revision, sparse, kernel, loading)
    return forward, meta, mod


def model_metadata(model, mod, snapshot, model_id, revision, sparse, kernel, loading):
    config = model.config
    # NOSA-3B has explicit head_dim=128, not hidden_size/num_attention_heads=80.
    head_dim = model.model.layers[0].self_attn.head_dim
    assert all(p.device.type == 'cuda' for p in model.parameters())
    assert {p.dtype for p in model.parameters()} == {torch.bfloat16}
    return dict(model=model_id, revision=revision, checkpoint=str(snapshot), layers=len(model.model.layers),
                kv_heads=config.num_key_value_heads, head_dim=head_dim,
                kv_bytes_per_token_per_layer=2 * config.num_key_value_heads * head_dim * 2,
                sparse_config=dict(sparse), vocab=config.vocab_size,
                parameters=sum(p.numel() for p in model.parameters()), dtype='bfloat16',
                retained_kv=True, loading=loading, model_code_sha256=sha(mod.__file__),
                config_sha256=sha(snapshot / 'config.json'), kernel_module=str(kernel.__file__),
                kernel_module_sha256=sha(kernel.__file__),
                checkpoint_weights={p.name: dict(bytes=p.stat().st_size, sha256=sha(p))
                                    for p in sorted(snapshot.glob('*.safetensors')) or sorted(snapshot.glob('pytorch_model*.bin'))})


def validate_forward(forward, mod, ids, meta):
    """Untimed shape warmup: require real native selection in every layer and full retained KV."""
    calls = []
    original = mod.compressed_attention

    def observed(*args, **kwargs):
        selected = original(*args, **kwargs)
        assert selected.dtype == torch.int32
        calls.append(list(selected.shape))
        return selected

    mod.compressed_attention = observed
    try:
        output = forward(ids)
        torch.cuda.synchronize()
        assert torch.isfinite(output.logits).all()
        assert len(calls) == meta['layers'], (len(calls), meta['layers'])
        cache = output.past_key_values
        lengths = [int(cache.get_seq_length(layer)) for layer in range(meta['layers'])]
        assert lengths == [ids.shape[1]] * meta['layers'], lengths
        return dict(native_selector_calls=len(calls), selection_shapes=calls, cache_lengths=lengths,
                    logits_finite=True, all_layer_kv_retained=True)
    finally:
        mod.compressed_attention = original


def timed(forward, ids, repeats):
    samples = []
    for _ in range(repeats):
        torch.cuda.synchronize()
        start = time.perf_counter()
        output = forward(ids)
        torch.cuda.synchronize()
        samples.append(time.perf_counter() - start)
        assert torch.isfinite(output.logits).all()
        # Keep KV alive through timing, then release before the next empty-cache forward.
        del output
    return samples


def gpu_snapshot():
    fields = 'uuid,name,driver_version,memory.total,memory.used,utilization.gpu,power.limit,clocks.sm,temperature.gpu'
    inventory = subprocess.check_output(['nvidia-smi', '--query-gpu=' + fields, '--format=csv,noheader,nounits'], text=True)
    processes = subprocess.check_output(['nvidia-smi', '--query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory',
                                         '--format=csv,noheader,nounits'], text=True)
    uuid = str(torch.cuda.get_device_properties(0).uuid)
    if not uuid.startswith('GPU-'):
        uuid = 'GPU-' + uuid
    foreign = [line for line in processes.splitlines() if line.split(',')[0].strip() == uuid
               and int(line.split(',')[1].strip()) != os.getpid()]
    assert not foreign, ('GPU already has another compute process; refusing contaminated measurement', foreign)
    return dict(gpu_fields=fields, inventory=inventory.splitlines(), compute_processes=processes.splitlines(),
                selected_gpu_uuid=uuid, pid=os.getpid(), foreign_processes=foreign)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=['minicpm4-8b', *NOSA], required=True)
    parser.add_argument('--contexts', type=int, nargs='+', default=[8192, 16384, 32768, 65536, 98304, 131072])
    parser.add_argument('--tail', type=int, default=0, help='Optional marginal full-prefill probe; not cached replay')
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--out-tag', required=True, help='Unique suffix; existing result files are never overwritten')
    args = parser.parse_args()
    assert args.repeats >= 1 and args.tail >= 0 and min(args.contexts) >= 8192
    assert args.out_tag and '/' not in args.out_tag
    path = OUT / f'prefill-latency-{args.model}-{args.out_tag}.json'
    if path.exists():
        raise FileExistsError(path)
    assert torch.cuda.is_available()
    torch.set_num_threads(min(8, int(os.environ.get('SLURM_CPUS_PER_TASK', '8'))))
    torch.manual_seed(20260915)
    result = dict(status='loading', protocol_version=2, args=vars(args), rows=[], skipped_out_of_memory=[],
                  started_at=datetime.now(timezone.utc).isoformat(), gpu=torch.cuda.get_device_name(0), host=platform.node(),
                  slurm_job_id=os.environ.get('SLURM_JOB_ID'), torch=torch.__version__, cuda=torch.version.cuda,
                  versions={p: importlib.metadata.version(p) for p in ('transformers', 'triton', 'accelerate', 'numpy')},
                  script_sha256=sha(__file__),
                  protocol='BF16, batch 1, random-token input, native sparse full causal prefill, empty cache per forward, '
                           'all layer KV retained through CUDA synchronization; wall-clock includes selection and KV writes; '
                           'one untimed validated warmup at every shape; repeated timings on same input, not independent workloads')

    def persist():
        temp = path.with_suffix('.json.tmp')
        temp.write_text(json.dumps(result, indent=2) + '\n')
        temp.replace(path)

    persist()
    try:
        result['gpu_before'] = gpu_snapshot()
        persist()
        forward, meta, mod = load_minicpm4() if args.model == 'minicpm4-8b' else load_nosa(args.model)
        result.update(meta=meta, status='running')
        persist()
        for length in sorted(set(args.contexts)):
            # Same model vocab + same context => identical input regardless of attempted context list.
            generator = torch.Generator(device='cpu').manual_seed(1 + length)
            cpu_ids = torch.randint(100, meta['vocab'] - 100, (1, length + args.tail), generator=generator)
            input_sha = hashlib.sha256(cpu_ids.numpy().tobytes()).hexdigest()
            ids = cpu_ids.to('cuda')
            phase = 'warmup'
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
            try:
                before = gpu_snapshot()
                validation = validate_forward(forward, mod, ids[:, :length], meta)
                phase = 'prefill'
                full = timed(forward, ids[:, :length], args.repeats)
                row = dict(context=length, input_ids_sha256=input_sha, input_seed=1 + length,
                           prefill_s=full, prefill_median_s=statistics.median(full),
                           validation=validation, peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
                           gpu_before=before, gpu_after=gpu_snapshot())
                if args.tail:
                    phase = 'optional_marginal_probe'
                    try:
                        validate_forward(forward, mod, ids, meta)
                        tail = timed(forward, ids, args.repeats)
                        row.update(tail=args.tail, prefill_tail_s=tail,
                                   tail_marginal_median_s=statistics.median(tail) - statistics.median(full))
                    except torch.OutOfMemoryError as exc:
                        row['optional_tail_oom'] = str(exc).splitlines()[0][:300]
                result['rows'].append(row)
                print('CTX', length, 'prefill', round(row['prefill_median_s'], 4), 's',
                      'peak GiB', round(row['peak_cuda_allocated_bytes'] / 2**30, 2), 'retained KV OK', flush=True)
            except torch.OutOfMemoryError as exc:
                result['skipped_out_of_memory'].append(dict(context=length, phase=phase, error=str(exc).splitlines()[0][:300]))
                print('CTX', length, phase, 'OOM', flush=True)
            finally:
                del ids
                torch.cuda.empty_cache()
                persist()
        result.update(status='complete', gpu_after=gpu_snapshot(), finished_at=datetime.now(timezone.utc).isoformat())
        persist()
    except Exception as exc:
        result.update(status='failed', error=repr(exc), finished_at=datetime.now(timezone.utc).isoformat())
        persist()
        raise
    print('WROTE', path, flush=True)


if __name__ == '__main__':
    main()
