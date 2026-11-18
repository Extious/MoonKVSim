"""Passively capture masks consumed by the pinned SeerAttention Prefill kernel.

Published full weights, original checkpoint source and original Triton kernel.
No fabricated scores, dense-attention replacement, or fault-latency claim.
"""
import argparse
import hashlib
import importlib
import importlib.metadata
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
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[4]
CHECKPOINT = ROOT / 'checkpoint'
TEXTS = ROOT.parent / 'runtime-20260914/data'
M, N, BLOCK = 32768, 512, 64


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2)+'\n')


class Observer:
    def __init__(self, module, kernel, model):
        self.enabled = False
        self.layer = None
        self.records = {}
        self.selected = None
        self.original_select = module.get_sparse_attn_mask_from_threshold
        self.original_kernel = kernel._forward
        module.get_sparse_attn_mask_from_threshold = self.select
        kernel._forward = self.forward
        for layer in model.model.layers:
            layer.self_attn.register_forward_pre_hook(self.before)
            layer.self_attn.register_forward_hook(self.after)

    def start(self, out, history, suffix):
        self.out = out
        out.mkdir(parents=True, exist_ok=True)
        self.history, self.suffix = history, suffix
        self.records = {}
        self.enabled = True

    def before(self, module, args):
        if self.enabled:
            self.layer = module.layer_idx
            assert self.layer not in self.records
            self.records[self.layer] = dict(layer_zero_based=self.layer, select_calls=0, native_kernel_calls=0)

    def select(self, *args, **kwargs):
        result = self.original_select(*args, **kwargs)
        if self.enabled:
            row = self.records[self.layer]
            row['select_calls'] += 1
            assert result.dtype == torch.bool
            self.selected = result
        return result

    def forward(self, ctx, q, k, v, mask, *args, **kwargs):
        if self.enabled:
            assert mask is self.selected, 'Captured selector output is not the mask consumed by the native kernel'
            row = self.records[self.layer]
            row['native_kernel_calls'] += 1
            a = mask.detach().cpu().numpy()
            blocks = (self.history+self.suffix)//BLOCK
            assert a.shape == (1, 32, blocks, blocks), a.shape
            assert not np.any(np.triu(a, 1))
            assert np.all(a.sum(-1) > 0)
            path = self.out / f'layer-{self.layer+1:02d}.npz'
            np.savez_compressed(path, block_mask=a[0])
            row.update(selection_shape=list(a.shape), native_mask_identity_verified=True,
                       trace_format='query_head_query_block_key_block_bool',
                       causal_and_nonempty=True, trace_file=str(path.relative_to(ROOT)),
                       trace_sha256=sha(path), valid_block_selections=int(a.sum()))
        return self.original_kernel(ctx, q, k, v, mask, *args, **kwargs)

    def after(self, module, args, output):
        if self.enabled:
            row = self.records[self.layer]
            row['output_finite'] = bool(torch.isfinite(output[0]).all().item())
            assert row['output_finite'] and row['select_calls'] == row['native_kernel_calls'] == 1, row
            print('LAYER', self.layer+1, 'OK', flush=True)
            self.layer = None
            self.selected = None

    def finish(self):
        self.enabled = False
        assert sorted(self.records) == list(range(32))
        return [self.records[i] for i in range(32)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--books', nargs='+', default=['10146','10321','10356'])
    args = parser.parse_args()
    verification = json.loads((ROOT/'checkpoint-verification.json').read_text())
    assert verification['status'] == 'verified'
    for name, record in verification['files'].items():
        assert sha(CHECKPOINT/name) == record['sha256'], name
    package = types.ModuleType('seer_checkpoint')
    package.__path__ = [str(CHECKPOINT)]
    sys.modules[package.__name__] = package
    module = importlib.import_module('seer_checkpoint.modeling_llama_seerattn')
    kernel = importlib.import_module('seer_checkpoint.block_sparse_attn')
    config_module = importlib.import_module('seer_checkpoint.configuration_llama_seerattn')
    config = config_module.SeerAttnLlamaConfig.from_pretrained(CHECKPOINT, local_files_only=True)
    config.seerattn_sparsity_method = 'threshold'
    config.seerattn_threshold = 2e-3  # Published checkpoint card's evaluation setting.
    # Avoid changing which query blocks are forced dense when a retry ends earlier.
    # This is an explicit published configuration option, not a patched selector.
    config.seerattn_last_block_dense = False
    config._attn_implementation = 'sdpa'
    model, loading = module.SeerAttnLlamaForCausalLM.from_pretrained(
        CHECKPOINT, config=config, torch_dtype=torch.bfloat16, device_map={'':'cuda:0'},
        local_files_only=True, output_loading_info=True, attn_implementation='sdpa')
    write(ROOT/'loading.json', loading)
    assert not any(loading.get(k) for k in ['missing_keys','unexpected_keys','mismatched_keys','error_msgs']), loading
    model.eval()
    assert all(isinstance(x.self_attn, module.LlamaSeerAttention) for x in model.model.layers)
    tokenizer = AutoTokenizer.from_pretrained(CHECKPOINT, local_files_only=True)
    env = dict(model='SeerAttention-Llama-3.1-8B', revision=verification['revision'],
               checkpoint_verification_sha256=sha(ROOT/'checkpoint-verification.json'),
               capture_script_sha256=sha(__file__), slurm_job_id=os.getenv('SLURM_JOB_ID'),
               host=platform.node(), gpu=torch.cuda.get_device_name(),
               packages={x:importlib.metadata.version(x) for x in ['torch','transformers','triton','numpy','tokenizers']},
               native_layer_config=dict(block_size=64, query_block_size=64, init_blocks=0, local_blocks=0,
                                        sparsity_method='threshold', threshold=2e-3, last_block_dense=False),
               kv_layout=dict(layers=32, query_heads=32, kv_heads=8, head_dim=128,
                              block_tokens=64, block_bytes_layer=2*2*8*128*64),
               evidence='Native full Prefill with published full weights; masks pass unchanged to original Triton kernel.',
               config_note='Published threshold 2e-3; disable optional last-two-query-block dense override so a shorter retry does not change that rule. No sparse quality or failure-latency measurement.')
    write(ROOT/'measured-environment.json', env)
    observer = Observer(module, kernel, model)
    data = {book:tokenizer((TEXTS/f'{book}.txt').read_text(), add_special_tokens=True)['input_ids'] for book in args.books}

    def forward(ids):
        x = torch.tensor([ids], device='cuda', dtype=torch.long)
        with torch.inference_mode():
            out = model(input_ids=x, attention_mask=None, use_cache=False,
                        output_attentions=False, num_logits_to_keep=1)
        return out.logits.detach().float().cpu()

    small = data[args.books[0]][:1024]
    baseline = forward(small)
    observer.start(ROOT/'validation', 512, 512)
    traced = forward(small)
    records = observer.finish()
    delta = float((baseline-traced).abs().max())
    assert delta == 0 and torch.isfinite(traced).all(), delta
    write(ROOT/'observer-validation.json', dict(max_abs_logit_delta=delta, layers=records,
                                               logits_finite=True, status='passed'))
    for book in args.books:
        assert len(data[book]) >= M+N
        folder = ROOT/'traces'/f'pg19-{book}-M{M}-N{N}'
        ids = data[book][:M+N]
        folder.mkdir(parents=True, exist_ok=True)
        np.save(folder/'input_ids.npy', np.asarray(ids, dtype=np.int64))
        run = dict(status='running', book_id=book, M=M, N=N,
                   text_sha256=sha(TEXTS/f'{book}.txt'), input_ids_sha256=sha(folder/'input_ids.npy'))
        write(folder/'run.json', run)
        observer.start(folder, M, N)
        torch.cuda.reset_peak_memory_stats()
        start = time.monotonic()
        try:
            logits = forward(ids)
            layers = observer.finish()
            assert bool(torch.isfinite(logits).all())
            run.update(status='complete', layers=layers, logits_finite=True,
                       elapsed_seconds=time.monotonic()-start,
                       peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                       greedy_next_token_id=int(logits[0,-1].argmax()))
            write(folder/'run.json', run)
            print('DOCUMENT_COMPLETE', book, run['elapsed_seconds'], flush=True)
        except Exception as exc:
            run.update(status='failed', error=repr(exc))
            write(folder/'run.json', run)
            raise
    print('CAPTURE_COMPLETE', flush=True)


if __name__ == '__main__':
    main()
