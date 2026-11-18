"""Observe the published NOSA-1B/3B/8B forward pass; never synthesize selection scores.

The checkpoint code and native CUDA selection/attention are unmodified. Pure
padding utilities are loaded directly from the author's dependency tree because
the checkpoint groups an unused dense FlashAttention import with required sparse
imports in one broad try/except. This bootstrap changes no attention computation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import types

import numpy as np
import torch
from transformers import AutoTokenizer, LlamaConfig

PROJECT = Path('/home/comp/zhanzhao/MoonKVSim')
ROOT = PROJECT / 'benchmark/AegisKV/experiments/native-sparse/runtime-20260914'
OUT = PROJECT / 'benchmark/AegisKV/experiments/native-sparse/20260914'
CHECKPOINT = ROOT / 'NOSA-1B'
SOURCE = ROOT / 'upstream/source/NOSA-1cbee77d607f9051b206a09c862bea28becb9e67'
KERNEL_ROOT = SOURCE / 'dependencies/infllmv2_cuda_impl'
REVISION = '7bdc33fbc1bc80b76b29689ba35ff6a7991b7dee'
MODEL_SPECS = {
    'NOSA-1B': dict(revision=REVISION, layers=28),
    'NOSA-3B': dict(revision='c5a4d505d5811f7555d786a031a4623787da7fb0', layers=32,
                    weight_bytes=7211741880,
                    weight_sha256='991609e62adbec10654d25e8b16f62faedc457feeb3ba9ef8b88eeeea1cad3c1'),
    'NOSA-8B': dict(revision='6da5609664fa64ea55125a32e7cb70f541d97ea9', layers=32,
                    total_tokens_exclusive_limit=32768,  # Pinned cis_pooling.py: max_seqlen < MAX_LEN
                    weight_bytes=16370581512,
                    weight_sha256='5219c9ec34c4a19650e98b079ccf4911ffb3457e8f67690ca9037c09e89fd477'),
}


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def gpu_snapshot():
    """Reject foreign work only on the GPU assigned to this capture, never other cards."""
    uuid = str(torch.cuda.get_device_properties(0).uuid)
    if not uuid.startswith('GPU-'):
        uuid = 'GPU-' + uuid
    processes = subprocess.check_output(
        ['nvidia-smi', '--query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory',
         '--format=csv,noheader,nounits'], text=True).splitlines()
    foreign = [row for row in processes if row.split(',')[0].strip() == uuid
               and int(row.split(',')[1].strip()) != os.getpid()]
    if foreign:
        raise RuntimeError(f'Foreign GPU processes found on {uuid}; refusing to interfere: {foreign}')
    return dict(selected_gpu_uuid=uuid, pid=os.getpid(), compute_processes=processes,
                foreign_processes=foreign)


def bootstrap():
    sys.path.insert(0, str(KERNEL_ROOT))
    import infllm_v2
    native = importlib.import_module('infllm_v2.infllmv2_sparse_attention')
    pkg = types.ModuleType('nosa_checkpoint')
    pkg.__path__ = [str(CHECKPOINT)]
    sys.modules[pkg.__name__] = pkg
    mod = importlib.import_module('nosa_checkpoint.modeling_llama_long_infllmv2')
    path = SOURCE / 'dependencies/flash-attention-nosa/flash_attn_nosa/bert_padding.py'
    spec = importlib.util.spec_from_file_location('nosa_official_padding', path)
    padding = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(padding)
    for name in ('index_first_axis', 'pad_input', 'unpad_input'):
        setattr(mod, name, getattr(padding, name))
    for name in ('infllmv2_attn_stage1', 'infllmv2_attn_varlen_func',
                 'infllmv2_attn_with_kvcache', 'max_pooling_1d', 'max_pooling_1d_varlen'):
        setattr(mod, name, getattr(infllm_v2, name))

    def forbid_dense(*args, **kwargs):
        raise AssertionError('Unexpected dense attention path; this run requires native sparsity')

    mod.flash_attn_func = forbid_dense
    mod.flash_attn_varlen_func = forbid_dense
    return mod, native, infllm_v2, path


class Observer:
    def __init__(self, mod, native, model):
        self.enabled = False
        self.layers = len(model.model.layers)
        self.kv_heads = model.config.num_key_value_heads
        self.mod = mod
        self.native = native
        self.layer = None
        self.records = {}
        self.selected = None
        self.original_select = mod.compressed_attention
        self.original_pack = native.cuda_topk_to_uint64
        mod.compressed_attention = self.select
        native.cuda_topk_to_uint64 = self.pack
        for layer in model.model.layers:
            layer.self_attn.register_forward_pre_hook(self.before_layer)
            layer.self_attn.register_forward_hook(self.after_layer)

    def start(self, run_dir, history, suffix):
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.history, self.suffix = history, suffix
        self.records = {}
        self.enabled = True

    def before_layer(self, module, args):
        if self.enabled:
            self.layer = module.layer_idx
            assert self.layer not in self.records
            self.records[self.layer] = {'layer_zero_based': self.layer,
                                       'attention_class': type(module).__name__,
                                       'select_calls': 0, 'native_mask_calls': 0}

    def after_layer(self, module, args, output):
        if self.enabled:
            row = self.records[self.layer]
            row['output_finite'] = bool(torch.isfinite(output[0]).all().item())
            assert row['output_finite'], (self.layer, 'nonfinite native layer output')
            assert row['select_calls'] == 1 and row['native_mask_calls'] == 2, row
            print('LAYER', self.layer + 1, 'shape', row['selection_shape'],
                  'native_masks_checked', row['native_mask_calls'], flush=True)
            self.layer = None

    def select(self, *args, **kwargs):
        result = self.original_select(*args, **kwargs)
        if self.enabled:
            row = self.records[self.layer]
            row['select_calls'] += 1
            assert result.dtype == torch.int32
            arr = result.detach().cpu().numpy()
            assert arr.shape[:2] == (self.kv_heads, self.history + self.suffix), arr.shape
            assert arr.min() >= -1
            q_block = np.arange(arr.shape[1])[None, :, None] // 64
            assert np.all((arr < 0) | (arr <= q_block))
            valid = arr >= 0
            assert np.all(valid.sum(axis=-1) > 0)
            assert not np.any((np.diff(arr, axis=-1) == 0) & valid[:, :, 1:])
            row['selection_shape'] = list(arr.shape)
            row['causal_and_unique'] = True
            row['original_selection_dtype'] = str(arr.dtype)
            row['valid_selections'] = int(valid.sum())
            row['cached_history_selections_in_suffix'] = int(
                ((arr[:, self.history:] >= 0) &
                 (arr[:, self.history:] < self.history // 64)).sum())
            # int16 is lossless for the fixed context lengths (< 32768 blocks).
            assert arr.max() < 32768
            path = self.run_dir / f'layer-{self.layer + 1:02d}.npz'
            np.savez_compressed(path, selected_blocks=arr.astype(np.int16))
            row['trace_file'] = str(path.relative_to(OUT))
            row['trace_sha256'] = digest(path)
            self.selected = arr
        return result

    def pack(self, *args, **kwargs):
        result = self.original_pack(*args, **kwargs)
        if self.enabled:
            row = self.records[self.layer]
            row['native_mask_calls'] += 1
            # These are the actual bitmasks returned to each native stage-2 call.
            start = max(0, self.history - self.suffix)
            actual = result[0][:, start:].detach().cpu().numpy().view(np.uint64)
            idx = self.selected[:, start:]
            expected = np.zeros_like(actual)
            head, query, rank = np.nonzero(idx >= 0)
            block = idx[head, query, rank].astype(np.int64)
            np.bitwise_or.at(expected, (head, query, block // 64),
                             np.left_shift(np.uint64(1), (block % 64).astype(np.uint64)))
            assert np.array_equal(actual, expected), (self.layer, 'native mask mismatch')
            row['native_mask_checked_query_range'] = [start, self.history + self.suffix]
            row['native_mask_equals_selected_blocks'] = True
            if row['native_mask_calls'] == 1:
                np.savez_compressed(self.run_dir / f'layer-{self.layer + 1:02d}-mask.npz',
                                    packed_mask=actual, query_start=np.int64(start))
        return result

    def finish(self):
        self.enabled = False
        assert sorted(self.records) == list(range(self.layers))
        return [self.records[k] for k in sorted(self.records)]


def main():
    global CHECKPOINT, OUT, REVISION
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=MODEL_SPECS, default='NOSA-1B')
    parser.add_argument('--out-dir', type=Path, help='New models default to separate model-specific output directories')
    parser.add_argument('--histories', type=int, nargs='+', default=[16384, 32768])
    parser.add_argument('--suffix', type=int, default=512)
    parser.add_argument('--books', nargs='+', default=['10146', '10321', '10356'])
    parser.add_argument('--run-tag', default='measured')
    args = parser.parse_args()
    spec = MODEL_SPECS[args.model]
    CHECKPOINT, REVISION = ROOT / args.model, spec['revision']
    if args.out_dir:
        OUT = args.out_dir.resolve()
    elif args.model != 'NOSA-1B':
        OUT = PROJECT / 'benchmark/AegisKV/experiments/native-sparse' / f'20260915-{args.model.lower()}'
    assert all(h > 0 and h % 64 == 0 for h in args.histories)
    assert args.suffix > 0 and args.suffix % 64 == 0
    total_limit = spec.get('total_tokens_exclusive_limit')
    if total_limit is not None and any(h + args.suffix >= total_limit for h in args.histories):
        parser.error(
            f'{args.model} at revision {REVISION} requires history + suffix < {total_limit} '
            '(published cis_pooling.py limit); use a shorter history and do not mix it '
            'into the fixed-32K comparison. No model or kernel source is patched.')
    # Fail before creating a CUDA context if another campaign is still downloading the weights.
    weights = sorted(CHECKPOINT.glob('*.safetensors')) or sorted(CHECKPOINT.glob('pytorch_model*.bin'))
    if not weights:
        raise FileNotFoundError(f'Complete model weights are not available: {CHECKPOINT}')
    if 'weight_sha256' in spec:
        path = CHECKPOINT / 'model.safetensors'
        assert path.stat().st_size == spec['weight_bytes'], path
        assert digest(path) == spec['weight_sha256'], path
    if (OUT / f'{args.run_tag}-environment.json').exists():
        raise FileExistsError('Use a new --out-dir or --run-tag; never overwrite a capture environment')
    assert os.environ.get('SLURM_JOB_ID'), 'GPU capture requires a scheduler allocation'
    assert torch.cuda.is_available()
    gpu_before = gpu_snapshot()
    torch.manual_seed(20260914)
    torch.set_num_threads(min(8, int(os.environ.get('SLURM_CPUS_PER_TASK', '8'))))
    mod, native, kernel, padding_path = bootstrap()
    env = {
        'phase': 'actual GPU full causal sparse prefill, batch=1, no KV offloading',
        'claim_boundary': 'selected main-KV blocks, not attention mass or HBM transaction counts',
        'model': 'openbmb/' + args.model, 'revision': REVISION,
        'published_parameter_name': args.model,
        'checkpoint_weights': {p.name: dict(bytes=p.stat().st_size, sha256=digest(p)) for p in weights},
        'upstream_nosa_commit': '1cbee77d607f9051b206a09c862bea28becb9e67',
        'checkpoint_manifest_sha256': digest(ROOT / 'CHECKPOINT_MANIFEST.json') if args.model == 'NOSA-1B' else None,
        'model_code_sha256': digest(mod.__file__),
        'pooling_code_sha256': digest(CHECKPOINT / 'cis_pooling.py'),
        'config_sha256': digest(CHECKPOINT / 'config.json'),
        'padding_code_sha256': digest(padding_path),
        'bootstrap': 'directly bind original padding and infllm_v2 imports; no model/kernel source edits',
        'script_sha256': digest(__file__),
        'host': platform.node(), 'slurm_job_id': os.environ.get('SLURM_JOB_ID'),
        'gpu': torch.cuda.get_device_name(0),
        'gpu_before': gpu_before,
        'gpu_capability': list(torch.cuda.get_device_capability(0)),
        'torch_cuda': torch.version.cuda,
        'versions': {n: importlib.metadata.version(n) for n in
                     ['torch', 'transformers', 'triton', 'tokenizers', 'accelerate', 'numpy']},
        'args': {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
    }
    env_path = OUT / f'{args.run_tag}-environment.json'
    write_json(env_path, env)
    config = LlamaConfig.from_pretrained(CHECKPOINT, local_files_only=True)
    config._attn_implementation = 'sdpa'
    model, loading = mod.SparseLlamaForCausalLM.from_pretrained(
        CHECKPOINT, config=config, torch_dtype=torch.bfloat16,
        device_map={'': 'cuda:0'}, output_loading_info=True, local_files_only=True,
        attn_implementation='sdpa')
    write_json(OUT / f'{args.run_tag}-loading.json', loading)
    assert not any(loading.get(k) for k in ['missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs']), loading
    model.eval()
    assert len(model.model.layers) == spec['layers']
    for layer in model.model.layers:
        assert isinstance(layer.self_attn, mod.LlamaSdpaAttention)
        assert layer.self_attn.dense_len == 0 and layer.self_attn.topk == 64
    env['loaded_parameters'] = sum(p.numel() for p in model.parameters())
    attn = model.model.layers[0].self_attn
    env['kv_layout'] = dict(layers=len(model.model.layers), kv_heads=model.config.num_key_value_heads,
                            head_dim=attn.head_dim, block_tokens=attn.block_size,
                            block_bytes_layer=2 * 2 * model.config.num_key_value_heads * attn.head_dim * attn.block_size)
    assert env['kv_layout']['block_bytes_layer'] == 65536, env['kv_layout']
    env['learned_A_by_layer'] = [l.self_attn.A.detach().float().cpu().tolist() for l in model.model.layers]
    env['learned_delta_weight_norm'] = [float(l.self_attn.delta.weight.float().norm().item()) for l in model.model.layers]
    assert all(v > 0 for v in env['learned_delta_weight_norm'])
    env['native_layer_config'] = {k: getattr(model.model.layers[0].self_attn, k) for k in
                                  ['kernel_size', 'kernel_stride', 'block_size', 'window_size',
                                   'local_blocks', 'init_blocks', 'topk', 'dense_len']}
    write_json(env_path, env)
    print('MODEL_LOADED', env['loaded_parameters'], flush=True)
    tokenizer = AutoTokenizer.from_pretrained(CHECKPOINT, local_files_only=True)
    observer = Observer(mod, native, model)
    # Tokenize each checkpoint's real text; do not assume token IDs from another model are interchangeable.
    data = {book: tokenizer((ROOT / 'data' / f'{book}.txt').read_text(),
                            add_special_tokens=True)['input_ids'] for book in args.books}

    def forward(ids):
        tensor = torch.tensor([ids], device='cuda', dtype=torch.long)
        with torch.inference_mode():
            output = model(input_ids=tensor, attention_mask=torch.ones_like(tensor),
                           use_cache=False, output_attentions=False, num_logits_to_keep=1)
        return output.logits.detach().float().cpu()

    # A paired check that observation does not change actual model outputs.
    small = data[args.books[0]][:1024]
    baseline = forward(small)
    observer.start(OUT / 'validation' / args.run_tag, 512, 512)
    traced = forward(small)
    validation_layers = observer.finish()
    delta = float((baseline - traced).abs().max())
    assert delta == 0 and torch.isfinite(traced).all(), delta
    write_json(OUT / f'{args.run_tag}-observer-validation.json',
               {'paired_forward_max_abs_logit_diff': delta, 'layers': validation_layers})
    print('OBSERVER_VALIDATED', delta, flush=True)

    for history in args.histories:
        assert history % 64 == 0 and args.suffix % 64 == 0
        for book in args.books:
            n = history + args.suffix
            assert len(data[book]) >= n, (book, len(data[book]), n)
            ids = data[book][:n]
            run_dir = OUT / 'traces' / f'pg19-{book}-M{history}-N{args.suffix}'
            assert not (run_dir / 'run.json').exists(), f'Completed run already exists: {run_dir}'
            observer.start(run_dir, history, args.suffix)
            np.save(run_dir / 'input_ids.npy', np.asarray(ids, dtype=np.int32))
            torch.cuda.reset_peak_memory_stats()
            gpu_before_run = gpu_snapshot()
            start = time.monotonic()
            logits = forward(ids)
            torch.cuda.synchronize()
            layers = observer.finish()
            elapsed = time.monotonic() - start
            assert torch.isfinite(logits).all()
            np.save(run_dir / 'last_logits.npy', logits.numpy())
            greedy = int(logits[0, -1].argmax())
            result = {
                'status': 'complete', 'model': 'openbmb/' + args.model,
                'book_id': book, 'M': history, 'N': args.suffix,
                'query_window_zero_based_half_open': [history, n],
                'prediction_window_zero_based_half_open': [history - args.suffix, history],
                'input_source': f'https://storage.googleapis.com/deepmind-gutenberg/test/{book}.txt',
                'input_text_sha256': digest(ROOT / 'data' / f'{book}.txt'),
                'input_ids_sha256': digest(run_dir / 'input_ids.npy'),
                'environment_file': env_path.name,
                'physical_full_prefill_forwards': 1,
                'instrumented_wall_seconds_not_latency_benchmark': elapsed,
                'peak_cuda_allocated_bytes': torch.cuda.max_memory_allocated(),
                'gpu_before': gpu_before_run, 'gpu_after': gpu_snapshot(),
                'greedy_next_token_id': greedy, 'greedy_next_token': tokenizer.decode([greedy]),
                'logits_finite': True, 'layers': layers,
            }
            write_json(run_dir / 'run.json', result)
            print('RUN_COMPLETE', str(run_dir), 'seconds', round(elapsed, 2),
                  'peak_GiB', round(result['peak_cuda_allocated_bytes'] / 2**30, 2), flush=True)
    print('CAMPAIGN_COMPLETE', flush=True)


if __name__ == '__main__':
    main()
