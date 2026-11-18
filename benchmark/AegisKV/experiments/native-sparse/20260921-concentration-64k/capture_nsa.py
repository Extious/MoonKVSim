"""Passive observation of the released fasa-org/MiniCPM-4-8B-NSA model.

Keep the trained checkpoint's selector, compression, gates, RoPE, and attention math.
The released class named LlamaSdpaAttention implements its actual sparse path.
Record both native raw-KV top-k indices and compressed-branch dimensions. This is
an instrumented causal prefill, not a serving-speed or decode benchmark.
"""
from __future__ import annotations

import argparse
import ast
import textwrap
import importlib
import importlib.metadata
import importlib.util
import inspect
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

PROJECT = Path('/home/comp/zhanzhao/MoonKVSim')
BASE = PROJECT / 'benchmark/AegisKV/experiments/native-sparse'
CAMPAIGN = Path(__file__).resolve().parent
CHECKPOINT = BASE / 'runtime-20260921/NSA-8B'
REVISION = '126d6d657ce3b18d99f835ec0ef326e4899fa370'
SOURCE = BASE / 'runtime-20260914/upstream/source/NOSA-1cbee77d607f9051b206a09c862bea28becb9e67'
KERNEL_ROOT = BASE / 'runtime-20260915/infllmv2_cuda_impl'
TRITON_ROOT = BASE / 'runtime-20260921/native-sparse-attention-triton'
sys.path.insert(0, str(BASE / '20260915'))
import capture_minicpm4 as shared
from capture_minicpm4 import digest, write_json, PADDING, TEXTS
from capture_common import gpu_snapshot, device_map


def forbid_dense(*args, **kwargs):
    raise AssertionError('Non-native/dense attention path is forbidden')


def bootstrap():
    # Public OpenBMB native kernels (same pinned implementation as MiniCPM4.1).
    sys.path.insert(0, str(KERNEL_ROOT))
    sys.path.insert(0, str(TRITON_ROOT))
    import infllm_v2
    assert Path(infllm_v2.__file__).is_relative_to(KERNEL_ROOT), infllm_v2.__file__
    assert 'cu_seqlens_v' in str(inspect.signature(infllm_v2.infllmv2_attn_stage1))
    # The checkpoint imports MoBA but never calls it in its NSA implementation.
    # Make this unused dependency fail closed instead of installing another model.
    unused = types.ModuleType('moba')
    unused.moba_attn_varlen = forbid_dense
    sys.modules['moba'] = unused
    package = types.ModuleType('nsa_checkpoint')
    package.__path__ = [str(CHECKPOINT)]
    sys.modules[package.__name__] = package
    mod = importlib.import_module('nsa_checkpoint.modeling_llama_long_infllmv2')
    spec = importlib.util.spec_from_file_location('nsa_padding_helpers', PADDING)
    padding = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(padding)
    for name in ('index_first_axis', 'pad_input', 'unpad_input'):
        setattr(mod, name, getattr(padding, name))
    for name in ('infllmv2_attn_stage1', 'infllmv2_attn_varlen_func',
                 'infllmv2_attn_with_kvcache', 'max_pooling_1d', 'max_pooling_1d_varlen'):
        setattr(mod, name, getattr(infllm_v2, name))
    # The checkpoint uses the earlier stage-1 API, before separate V lengths.
    # Its compressed K and V have identical positions/lengths. Supply that
    # missing metadata without changing tensors, masks, scores or selection.
    def stage1(q, k, v, **kwargs):
        assert k.shape == v.shape
        return infllm_v2.infllmv2_attn_stage1(q, k, v, cu_seqlens_v=kwargs['cu_seqlens_k'], **kwargs)
    mod.infllmv2_attn_stage1 = stage1
    original_compressed_fwd = mod.compressed_attention_fwd
    def compressed_fwd(q, *args, **kwargs):
        # The released Triton launcher assumes the current CUDA device matches
        # Q. Explicitly set that context for layer placement across two GPUs.
        with torch.cuda.device(q.device):
            return original_compressed_fwd(q, *args, **kwargs)
    mod.compressed_attention_fwd = compressed_fwd
    mod.flash_attn_func = forbid_dense
    mod.flash_attn_varlen_func = forbid_dense
    mod._flash_attention_forward = forbid_dense
    mod.LlamaAttention.forward = forbid_dense
    mod.LlamaFlashAttention2.forward = forbid_dense
    # Head batches bound the compressed-branch workspace. The native stage-1
    # kernel, per-head softmax and value product remain the same operations.
    original_full = mod.compressed_attention
    tree = ast.parse(textwrap.dedent(inspect.getsource(original_full)))
    replacements = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and 'q.shape[0] == 1' == ast.unparse(node.test) and any(
                isinstance(x, ast.Name) and x.id == 'compressed_attention_fwd' for stmt in node.orelse for x in ast.walk(stmt)):
            node.orelse = ast.parse('comp_attn_output = _bounded_compressed(q, k, v, kernel_size, kernel_stride, cu_seqlens_q, cu_seqlens_k, max_seqlen_q, max_seqlen_k)').body
            replacements += 1
    assert replacements == 1
    def bounded(q, k, v, kernel_size, kernel_stride, cuq, cuk, maxq, maxk):
        output = torch.empty_like(q)
        group = q.shape[1] // k.shape[1]
        assert group % 4 == 0
        for head in range(0, q.shape[1], 4):
            kv_head = head // group
            qs, ks = q[:, head:head+4], k[:, kv_head:kv_head+1]
            vs = v[:, kv_head:kv_head+1].repeat_interleave(4, dim=1)
            score = mod.compressed_attention_fwd(qs, ks, kernel_size, kernel_stride,
                cuq, cuk, maxq, maxk, q.shape[-1] ** (-.5))
            score = mod.F.softmax(score, dim=-1)
            score[score.isnan()] = 0
            output[:, head:head+4] = torch.einsum('hnm,mhd->nhd', score, vs)
            del score, vs
        return output
    namespace = dict(vars(mod), _bounded_compressed=bounded)
    exec(compile(ast.fix_missing_locations(tree), '<bounded-native-NSA-head-batches>', 'exec'), namespace)
    mod.compressed_attention = namespace['compressed_attention']
    mod._original_full_compressed_attention = original_full
    return mod, infllm_v2


class Observer(shared.Observer):
    def select(self, *args, **kwargs):
        result = self.original_select(*args, **kwargs)
        selected, compressed_output = result
        if self.enabled:
            row = self.records[self.layer]
            row['select_calls'] += 1
            assert selected.dtype == torch.int32
            arr = selected.detach().cpu().numpy()
            assert arr.shape[:2] == (2, self.history + self.suffix), arr.shape
            assert arr.min() >= -1
            q_block = np.arange(arr.shape[1])[None, :, None] // 64
            assert np.all((arr < 0) | (arr <= q_block))
            valid = arr >= 0
            assert np.all(valid.sum(axis=-1) > 0)
            sorted_valid = np.sort(np.where(valid, arr, np.iinfo(np.int32).max), axis=-1)
            assert not np.any((np.diff(sorted_valid, axis=-1) == 0) &
                              (sorted_valid[:, :, 1:] != np.iinfo(np.int32).max))
            row['selection_shape'] = list(arr.shape)
            row['causal_and_unique'] = True
            row['valid_selections'] = int(valid.sum())
            row['cached_history_selections_in_suffix'] = int(
                ((arr[:, self.history:] >= 0) & (arr[:, self.history:] < self.history // 64)).sum())
            q, compressed_k, compressed_v = args[:3]
            row['compressed_key_shape'] = list(compressed_k.shape)
            row['compressed_value_shape'] = list(compressed_v.shape)
            row['compressed_kv_bytes_full_sequence'] = sum(x.numel() * x.element_size()
                                                         for x in (compressed_k, compressed_v))
            row['compressed_output_finite'] = bool(torch.isfinite(compressed_output).all().item())
            assert row['compressed_output_finite']
            row['compressed_branch_executed'] = True
            assert arr.max() < 32768
            path = self.run_dir / f'layer-{self.layer + 1:02d}.npz'
            np.savez_compressed(path, selected_blocks=arr.astype(np.int16))
            row['trace_file'] = str(path.relative_to(shared.OUT))
            row['trace_sha256'] = digest(path)
            self.selected_tensor = selected
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out-dir', required=True, type=Path)
    args = parser.parse_args()
    out = args.out_dir.resolve()
    shared.OUT = out
    assert not out.exists(), 'Preserve all prior attempts; choose a new directory'
    out.mkdir(parents=True)
    assert os.environ.get('SLURM_JOB_ID'), 'GPU capture requires a scheduler allocation'
    assert torch.cuda.is_available()
    provenance = json.loads((CAMPAIGN / 'NSA-8B-checkpoint-verification.json').read_text())
    assert provenance['status'] == 'verified' and provenance['revision'] == REVISION
    for name, entry in provenance['files'].items():
        assert digest(CHECKPOINT / name) == entry['sha256'], name
    sys.path.insert(0, str(BASE / '20260914'))
    torch.manual_seed(20260921)
    torch.set_num_threads(min(8, int(os.environ.get('SLURM_CPUS_PER_TASK', '8'))))
    mod, kernel = bootstrap()
    from transformers import AutoTokenizer
    config = mod.LlamaConfig.from_pretrained(CHECKPOINT, local_files_only=True)
    assert config.max_position_embeddings == 32768
    env = {
        'phase': 'actual GPU full causal sparse prefill, batch=1, no KV offloading',
        'claim_boundary': 'selected raw KV blocks; compressed branch separately recorded; not HBM traffic',
        'model': 'fasa-org/MiniCPM-4-8B-NSA', 'revision': REVISION,
        'published_max_position_embeddings': config.max_position_embeddings,
        'context_scope': '64K extrapolation with unchanged weights/RoPE/native kernels; published configuration is 32K',
        'memory_schedule': 'Compressed branch computed in batches of 4 Query heads using the original kernel/softmax/einsum; validated against full native head batch',
        'checkpoint_provenance': provenance,
        'kernel_package': str(KERNEL_ROOT), 'kernel_module': kernel.__file__,
        'kernel_binary': kernel.C.__file__, 'kernel_binary_sha256': digest(kernel.C.__file__),
        'kernel_commit': subprocess.check_output(
            ['git', '-C', str(KERNEL_ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
        'kernel_source_hashes': {str(p.relative_to(KERNEL_ROOT)): digest(p)
                                 for p in sorted((KERNEL_ROOT / 'infllm_v2').glob('*.py'))},
        'native_sparse_attention_commit': subprocess.check_output(
            ['git', '-C', str(TRITON_ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
        'padding_code_sha256': digest(PADDING), 'script_sha256': digest(__file__),
        'shared_observer_code_sha256': digest(shared.__file__),
        'dual_gpu_helper_sha256': digest(CAMPAIGN / 'capture_common.py'),
        'device_map': device_map(rotary=True),
        'bootstrap': 'Explicit native-kernel/padding imports; unused MoBA and dense paths raise; '
                     'sdpa dispatch selects checkpoint native LlamaSdpaAttention; stage-1 API adapter supplies '
                     'cu_seqlens_v=cu_seqlens_k for equal-length compressed K/V; native Triton launch is '
                     'guarded by the Q tensor CUDA device for dual-GPU placement; no attention-math edits',
        'host': platform.node(), 'slurm_job_id': os.environ['SLURM_JOB_ID'],
        'gpu': torch.cuda.get_device_name(0), 'gpu_before': gpu_snapshot(),
        'gpu_capability': list(torch.cuda.get_device_capability(0)), 'torch_cuda': torch.version.cuda,
        'versions': {name: importlib.metadata.version(name) for name in
                     ['torch', 'transformers', 'triton', 'tokenizers', 'accelerate', 'numpy']},
    }
    env_path = out / 'measured-environment.json'
    write_json(env_path, env)
    model, loading = mod.SparseLlamaForCausalLM.from_pretrained(
        CHECKPOINT, config=config, torch_dtype=torch.bfloat16, device_map=device_map(rotary=True),
        output_loading_info=True, local_files_only=True, attn_implementation='sdpa')
    write_json(out / 'measured-loading.json', loading)
    assert not any(loading.get(k) for k in ['missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs']), loading
    model.eval()
    assert len(model.model.layers) == 32
    for layer in model.model.layers:
        assert type(layer.self_attn) is mod.LlamaSdpaAttention
        assert layer.self_attn.num_key_value_heads == 2
    attn = model.model.layers[0].self_attn
    env['loaded_parameters'] = sum(p.numel() for p in model.parameters())
    env['kv_layout'] = dict(layers=32, kv_heads=2, head_dim=attn.head_dim,
                            block_tokens=attn.block_size,
                            block_bytes_layer=2 * 2 * 2 * attn.head_dim * attn.block_size)
    env['native_layer_config'] = {k: getattr(attn, k) for k in
                                  ['kernel_size', 'kernel_stride', 'block_size', 'window_size',
                                   'local_blocks', 'init_blocks', 'topk', 'dense_len', 'use_nope']}
    assert env['native_layer_config']['topk'] == 64
    env['attn_implementation'] = model.config._attn_implementation
    write_json(env_path, env)
    print('MODEL_LOADED', env['loaded_parameters'], env['native_layer_config'], flush=True)
    tokenizer = AutoTokenizer.from_pretrained(CHECKPOINT, local_files_only=True, trust_remote_code=True)
    data = {}
    for book in ('10321', '10356', '10762'):
        data[book] = tokenizer((Path(__file__).with_name('texts') / f'{book}.txt').read_text(), add_special_tokens=True)['input_ids']
        write_json(out / 'provenance' / f'pg19-{book}-tokens.json', {
            'book_id': book, 'text_sha256': digest(Path(__file__).with_name('texts') / f'{book}.txt'),
            'tokens': len(data[book]), 'tokenizer': env['model'], 'revision': REVISION})
        print('TOKENIZED', book, len(data[book]), flush=True)
    observer = Observer(mod, model)

    def forward(ids):
        tensor = torch.tensor([ids], device='cuda', dtype=torch.long)
        with torch.inference_mode():
            output = model(input_ids=tensor, attention_mask=torch.ones_like(tensor),
                           use_cache=False, output_attentions=False, num_logits_to_keep=1)
        logits = output.logits.detach().float().cpu()
        del output
        torch.cuda.empty_cache()
        return logits

    small = data['10321'][:8704]
    mod.compressed_attention = mod._original_full_compressed_attention
    baseline = forward(small)
    mod.compressed_attention = observer.select
    observer.start(out / 'validation/measured', 8192, 512)
    traced = forward(small)
    layers = observer.finish()
    delta = float((baseline - traced).abs().max())
    write_json(out / 'measured-observer-validation.json', {
        'paired_forward_max_abs_logit_diff': delta, 'input_tokens': len(small), 'layers': layers})
    assert torch.isfinite(traced).all() and delta == 0, delta
    print('OBSERVER_VALIDATED', delta, flush=True)
    for book, tokens in data.items():
        assert len(tokens) >= 65536
        ids = tokens[:65536]
        run_dir = out / 'traces' / f'pg19-{book}-M65024-N512'
        observer.start(run_dir, 65024, 512)
        np.save(run_dir / 'input_ids.npy', np.asarray(ids, dtype=np.int32))
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        before = gpu_snapshot()
        start = time.monotonic()
        logits = forward(ids)
        torch.cuda.synchronize()
        elapsed = time.monotonic() - start
        layers = observer.finish()
        assert torch.isfinite(logits).all()
        np.save(run_dir / 'last_logits.npy', logits.numpy())
        result = {
            'status': 'complete', 'model': env['model'], 'book_id': book, 'M': 65024, 'N': 512,
            'query_window_zero_based_half_open': [65024, 65536],
            'input_source': f'https://storage.googleapis.com/deepmind-gutenberg/test/{book}.txt',
            'input_text_sha256': digest(Path(__file__).with_name('texts') / f'{book}.txt'),
            'input_ids_sha256': digest(run_dir / 'input_ids.npy'),
            'environment_file': env_path.name, 'physical_full_prefill_forwards': 1,
            'instrumented_wall_seconds_not_latency_benchmark': elapsed,
            'peak_cuda_allocated_bytes': torch.cuda.max_memory_allocated(),
            'gpu_before': before, 'gpu_after': gpu_snapshot(),
            'greedy_next_token_id': int(logits[0, -1].argmax()),
            'logits_finite': True, 'layers': layers,
        }
        write_json(run_dir / 'run.json', result)
        print('RUN_COMPLETE', book, 'seconds', round(elapsed, 2), 'peak_GiB',
              round(result['peak_cuda_allocated_bytes'] / 2**30, 2), flush=True)
    print('CAMPAIGN_COMPLETE', flush=True)


if __name__ == '__main__':
    main()
