"""Observe published MiniCPM4-8B or MiniCPM4.1-8B native sparse forward passes.

Same protocol as benchmark/AegisKV/experiments/native-sparse/20260914/capture_native.py (NOSA-1B): the checkpoint code and the
native CUDA selection/attention kernels are unmodified; the observer passively records the block indices
that `compressed_attention` returns to the sparse attention kernel for every layer.  Nothing is
synthesised.  The dense FlashAttention path is forbidden; every observed request is longer than
`dense_len`, so the model runs its native sparse path for the whole prefill.

Bootstrap differences from the NOSA run (all documented, none touch attention math):
  * the checkpoint groups `flash_attn` and `infllm_v2` imports in one bare try/except; the venv has the
    NOSA-built `infllm_v2` kernels and no `flash_attn` distribution, so the sparse kernel functions and
    the pure padding helpers are bound explicitly;
  * transformers 4.56 refuses `flash_attention_2` without the flash_attn distribution; the checkpoint's
    sparse attention class asserts that implementation name, so the dispatch check is bypassed for this
    model class only.  The dense path it would guard is replaced by a function that raises.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import importlib.util
import inspect
import json
import os
import platform
import subprocess
import sys
import time
import types
from pathlib import Path

import numpy as np
import torch

PROJECT = Path('/home/comp/zhanzhao/MoonKVSim')
NOSA_ROOT = PROJECT / 'benchmark/AegisKV/experiments/native-sparse/runtime-20260914'
OUT = PROJECT / 'benchmark/AegisKV/experiments/native-sparse/20260915'
HF_HUB = NOSA_ROOT / 'hf-runtime-cache/hub/models--openbmb--MiniCPM4-8B'
SOURCE = NOSA_ROOT / 'upstream/source/NOSA-1cbee77d607f9051b206a09c862bea28becb9e67'
# Upstream OpenBMB/infllmv2_cuda_impl (the kernel package MiniCPM4 expects; the NOSA fork changed the stage-1 API).
KERNEL_ROOT = PROJECT / 'benchmark/AegisKV/experiments/native-sparse/runtime-20260915/infllmv2_cuda_impl'
PADDING = SOURCE / 'dependencies/flash-attention-nosa/flash_attn_nosa/bert_padding.py'
TEXTS = PROJECT / 'benchmark/AegisKV/experiments/native-sparse/20260914/provenance'
# Published sparse configuration from the MiniCPM4-8B model card (README "InfLLM v2" section).
SPARSE_CONFIG = {'kernel_size': 32, 'kernel_stride': 16, 'init_blocks': 1, 'block_size': 64,
                 'window_size': 2048, 'topk': 64, 'use_nope': False, 'dense_len': 8192}
LAYERS = 32
KV_HEADS = 2


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def snapshot_dir():
    snaps = sorted((HF_HUB / 'snapshots').iterdir())
    assert len(snaps) == 1, snaps
    return snaps[0]


def bootstrap(snapshot):
    sys.path.insert(0, str(KERNEL_ROOT))
    import infllm_v2
    assert Path(infllm_v2.__file__).is_relative_to(KERNEL_ROOT), infllm_v2.__file__
    assert 'cu_seqlens_v' in str(inspect.signature(infllm_v2.infllmv2_attn_stage1))
    pkg = types.ModuleType('minicpm4_checkpoint')
    pkg.__path__ = [str(snapshot)]
    sys.modules[pkg.__name__] = pkg
    mod = importlib.import_module('minicpm4_checkpoint.modeling_minicpm')
    spec = importlib.util.spec_from_file_location('nosa_official_padding', PADDING)
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
    # The sparse attention class asserts `flash_attention_2`; transformers would refuse it without the
    # flash_attn distribution.  Return the name unconditionally for this checkpoint's classes only.
    mod.MiniCPMPreTrainedModel._check_and_adjust_attn_implementation = (
        lambda self, attn_implementation, is_init_check=False: 'flash_attention_2')
    return mod, infllm_v2


class Observer:
    def __init__(self, mod, model):
        self.enabled = False
        self.mod = mod
        self.layer = None
        self.records = {}
        self.original_select = mod.compressed_attention
        self.original_sparse = mod.infllmv2_attn_varlen_func
        self.selected_tensor = None
        mod.compressed_attention = self.select
        mod.infllmv2_attn_varlen_func = self.sparse
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
                                        'attention_class': type(module).__name__, 'select_calls': 0,
                                        'native_sparse_calls': 0}

    def after_layer(self, module, args, output):
        if self.enabled:
            row = self.records[self.layer]
            row['output_finite'] = bool(torch.isfinite(output[0]).all().item())
            assert row['output_finite'], (self.layer, 'nonfinite native layer output')
            assert row['select_calls'] == 1 and row['native_sparse_calls'] == 1, row
            assert row['native_kernel_indices_equal_selected_blocks'], row
            print('LAYER', self.layer + 1, 'shape', row['selection_shape'], flush=True)
            self.layer = None
            self.selected_tensor = None

    def sparse(self, *args, **kwargs):
        if self.enabled:
            row = self.records[self.layer]
            selected = kwargs['topk_idx']
            assert selected is self.selected_tensor, 'Native kernel did not receive the observed selection tensor'
            row['native_sparse_calls'] += 1
            row['native_kernel_indices_equal_selected_blocks'] = True
        return self.original_sparse(*args, **kwargs)

    def select(self, *args, **kwargs):
        result = self.original_select(*args, **kwargs)
        if self.enabled:
            row = self.records[self.layer]
            row['select_calls'] += 1
            assert result.dtype == torch.int32
            arr = result.detach().cpu().numpy()
            assert arr.shape[:2] == (KV_HEADS, self.history + self.suffix), arr.shape
            assert arr.min() >= -1
            q_block = np.arange(arr.shape[1])[None, :, None] // 64
            assert np.all((arr < 0) | (arr <= q_block))
            valid = arr >= 0
            assert np.all(valid.sum(axis=-1) > 0)
            sorted_valid = np.sort(np.where(valid, arr, np.iinfo(np.int32).max), axis=-1)
            assert not np.any((np.diff(sorted_valid, axis=-1) == 0) & (sorted_valid[:, :, 1:] != np.iinfo(np.int32).max))
            row['selection_shape'] = list(arr.shape)
            row['causal_and_unique'] = True
            row['valid_selections'] = int(valid.sum())
            row['cached_history_selections_in_suffix'] = int(
                ((arr[:, self.history:] >= 0) & (arr[:, self.history:] < self.history // 64)).sum())
            assert arr.max() < 32768
            path = self.run_dir / f'layer-{self.layer + 1:02d}.npz'
            np.savez_compressed(path, selected_blocks=arr.astype(np.int16))
            row['trace_file'] = str(path.relative_to(OUT))
            row['trace_sha256'] = digest(path)
            self.selected_tensor = result
        return result

    def finish(self):
        self.enabled = False
        assert sorted(self.records) == list(range(LAYERS)), sorted(self.records)
        return [self.records[k] for k in sorted(self.records)]


def main():
    global OUT
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=['MiniCPM4-8B', 'MiniCPM4.1-8B'], default='MiniCPM4-8B')
    parser.add_argument('--out-dir', type=Path, help='Defaults to a model-specific directory for MiniCPM4.1')
    parser.add_argument('--histories', type=int, nargs='+', default=[16384, 32768])
    parser.add_argument('--suffix', type=int, default=512)
    parser.add_argument('--books', nargs='+', default=['10146', '10321', '10356'])
    parser.add_argument('--run-tag', default='measured')
    args = parser.parse_args()
    if args.out_dir:
        OUT = args.out_dir.resolve()
    elif args.model != 'MiniCPM4-8B':
        OUT = PROJECT / 'benchmark/AegisKV/experiments/native-sparse' / f'20260915-{args.model.lower()}'
    assert args.run_tag and '/' not in args.run_tag
    assert all(h > 0 and h % 64 == 0 for h in args.histories)
    assert args.suffix > 0 and args.suffix % 64 == 0
    assert all(h + args.suffix > SPARSE_CONFIG['dense_len'] for h in args.histories)
    if (OUT / f'{args.run_tag}-environment.json').exists():
        raise FileExistsError('Use a new output directory; never overwrite capture provenance')
    if args.model == 'MiniCPM4.1-8B':
        sys.path.insert(0, str(PROJECT / 'benchmark/AegisKV/experiments/native-sparse/20260915'))
        from prepare_minicpm41 import CHECKPOINT, REVISION, verify_checkpoint
        snapshot, revision = CHECKPOINT, REVISION
        checkpoint_provenance = verify_checkpoint(snapshot)
        published_config = json.loads((snapshot / 'config.json').read_text())
        if max(args.histories) + args.suffix > published_config['max_position_embeddings']:
            parser.error('Requested history + suffix exceeds the published MiniCPM4.1 context limit')
    else:
        snapshot = snapshot_dir()
        revision = snapshot.name
        checkpoint_provenance = dict(checkpoint_weights={
            p.name: dict(bytes=p.stat().st_size, sha256=digest(p)) for p in sorted(snapshot.glob('*.safetensors'))})
    assert os.environ.get('SLURM_JOB_ID'), 'GPU capture requires a scheduler allocation'
    sys.path.insert(0, str(PROJECT / 'benchmark/AegisKV/experiments/native-sparse/20260914'))
    from capture_common import gpu_snapshot, device_map
    assert torch.cuda.is_available()
    gpu_before = gpu_snapshot()
    torch.manual_seed(20260915)
    torch.set_num_threads(min(8, int(os.environ.get('SLURM_CPUS_PER_TASK', '8'))))
    mod, kernel = bootstrap(snapshot)
    from transformers import AutoTokenizer
    env = {
        'phase': 'actual GPU full causal sparse prefill, batch=1, no KV offloading',
        'claim_boundary': 'selected main-KV blocks, not attention mass or HBM transaction counts',
        'model': 'openbmb/' + args.model, 'revision': revision,
        'checkpoint_weights': checkpoint_provenance['checkpoint_weights'],
        'checkpoint_provenance': checkpoint_provenance,
        'config_sha256': digest(snapshot / 'config.json'),
        'sparse_attention': 'InfLLM v2 (native, trained-in); published sparse_config',
        'sparse_config': SPARSE_CONFIG,
        'kernel_package': 'upstream OpenBMB/infllmv2_cuda_impl, built in place for sm_80 (runs on RTX 4090 / A100)',
        'kernel_commit': subprocess.run(['git', '-C', str(KERNEL_ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip(),
        'model_code_sha256': digest(snapshot / 'modeling_minicpm.py'),
        'padding_code_sha256': digest(PADDING),
        'bootstrap': 'bind infllm_v2 kernels + padding helpers explicitly; bypass transformers FA2 dispatch check; '
                     'dense path replaced by an assertion',
        'script_sha256': digest(__file__),
        'dual_gpu_helper_sha256': digest(Path(__file__).with_name('capture_common.py')),
        'device_map': device_map(),
        'placement_note': 'Layers 0-15 on GPU 0, layers 16-31 on GPU 1; unchanged native per-layer attention',
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
    config = mod.MiniCPMConfig.from_pretrained(snapshot, local_files_only=True)
    config.sparse_config = dict(SPARSE_CONFIG)
    model, loading = mod.MiniCPMForCausalLM.from_pretrained(
        snapshot, config=config, torch_dtype=torch.bfloat16, device_map=device_map(),
        output_loading_info=True, local_files_only=True, attn_implementation='flash_attention_2')
    write_json(OUT / f'{args.run_tag}-loading.json', loading)
    assert not any(loading.get(k) for k in ['missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs']), loading
    model.eval()
    assert len(model.model.layers) == LAYERS
    for layer in model.model.layers:
        assert isinstance(layer.self_attn, mod.MiniCPMInfLLMv2Attention), type(layer.self_attn)
        assert layer.self_attn.dense_len == SPARSE_CONFIG['dense_len']
        assert layer.self_attn.num_key_value_heads == KV_HEADS
    env['loaded_parameters'] = sum(p.numel() for p in model.parameters())
    attn = model.model.layers[0].self_attn
    env['kv_layout'] = dict(layers=LAYERS, kv_heads=KV_HEADS, head_dim=attn.head_dim,
                            block_tokens=attn.block_size,
                            block_bytes_layer=2 * 2 * KV_HEADS * attn.head_dim * attn.block_size)
    assert env['kv_layout'] == dict(layers=32, kv_heads=2, head_dim=128,
                                    block_tokens=64, block_bytes_layer=65536)
    env['native_layer_config'] = {k: getattr(model.model.layers[0].self_attn, k) for k in
                                  ['kernel_size', 'kernel_stride', 'block_size', 'window_size',
                                   'local_blocks', 'init_blocks', 'topk', 'dense_len', 'use_nope']}
    env['attn_implementation'] = model.config._attn_implementation
    write_json(env_path, env)
    print('MODEL_LOADED', env['loaded_parameters'], env['native_layer_config'], flush=True)
    tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True)
    data = {}
    for book in args.books:
        text = (TEXTS / f'pg19-{book}.txt').read_text()
        ids = tokenizer(text, add_special_tokens=True)['input_ids']
        data[book] = ids
        write_json(OUT / 'provenance' / f'pg19-{book}-tokens.json',
                   {'book_id': book, 'text_sha256': digest(TEXTS / f'pg19-{book}.txt'), 'tokens': len(ids),
                    'tokenizer': 'openbmb/' + args.model, 'revision': revision})
        print('TOKENIZED', book, len(ids), flush=True)
    observer = Observer(mod, model)

    def forward(ids):
        tensor = torch.tensor([ids], device='cuda', dtype=torch.long)
        # The checkpoint's sparse path stores compressed keys in its own Cache subclass and rejects
        # past_key_values=None, so a fresh, empty InfLLMv2Cache is passed for every prefill.
        cache = mod.InfLLMv2Cache(config=model.config, num_hidden_layers=LAYERS)
        with torch.inference_mode():
            output = model(input_ids=tensor, attention_mask=torch.ones_like(tensor), past_key_values=cache,
                           use_cache=True, output_attentions=False, logits_to_keep=1)
        logits = output.logits.detach().float().cpu()
        del output, cache
        torch.cuda.empty_cache()
        return logits

    # Paired check that observation does not change model outputs (input longer than dense_len).
    small_len = SPARSE_CONFIG['dense_len'] + 512
    small = data[args.books[0]][:small_len]
    baseline = forward(small)
    observer.start(OUT / 'validation' / args.run_tag, small_len - 512, 512)
    traced = forward(small)
    validation_layers = observer.finish()
    delta = float((baseline - traced).abs().max())
    assert torch.isfinite(traced).all()
    write_json(OUT / f'{args.run_tag}-observer-validation.json',
               {'paired_forward_max_abs_logit_diff': delta, 'input_tokens': small_len, 'layers': validation_layers})
    print('OBSERVER_VALIDATED', delta, flush=True)
    assert delta == 0, delta

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
            torch.cuda.synchronize()
            gpu_before_run = gpu_snapshot()
            start = time.monotonic()
            logits = forward(ids)
            torch.cuda.synchronize()
            elapsed = time.monotonic() - start
            layers = observer.finish()
            assert torch.isfinite(logits).all()
            np.save(run_dir / 'last_logits.npy', logits.numpy())
            greedy = int(logits[0, -1].argmax())
            result = {
                'status': 'complete', 'model': 'openbmb/' + args.model, 'book_id': book, 'M': history, 'N': args.suffix,
                'query_window_zero_based_half_open': [history, n],
                'prediction_window_zero_based_half_open': [history - args.suffix, history],
                'input_source': f'https://storage.googleapis.com/deepmind-gutenberg/test/{book}.txt',
                'input_text_sha256': digest(TEXTS / f'pg19-{book}.txt'),
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
