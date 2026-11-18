"""Qwen1M 64K Prefill: published Qwen selector, native MInference CUDA/Triton.

At 64K the whole input is inside the first DCA chunk (262144-8192), so there
are no successive/inter-chunk branches or cross-fragment LSE merges. Load the
published Qwen selector function verbatim via AST and use its refined budgets.
Native MInference implements the sparse attention backend. Store the actual
packed kernel inputs, not an idealized vertical/slash mask. No speed claim.
"""
from __future__ import annotations
import ast
import hashlib
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
import types

import numpy as np
import torch
import torch.nn.functional as F
from transformers import AutoModelForCausalLM, AutoTokenizer
from transformers.models.qwen2.modeling_qwen2 import apply_rotary_pos_emb

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
RUNTIME = BASE / 'runtime-20260921'
CHECKPOINT = RUNTIME / 'Qwen2.5-7B-Instruct-1M'
MINFERENCE = RUNTIME / 'MInference'
M, N, B = 65024, 512, 64
BOOKS = ('10321', '10356', '10762')
sys.path.insert(0, str(HERE))
from capture_common import gpu_snapshot


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n')


def bootstrap():
    ready = json.loads((RUNTIME / 'minference-index-build/READY.json').read_text())
    assert sha(ready['library']) == ready['library_sha256']
    spec = importlib.util.spec_from_file_location('minference_index64', ready['library'])
    cuda = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cuda)
    # Avoid importing unused serving frameworks and their unrelated dependencies.
    for name, path in [('minference', MINFERENCE / 'minference'),
                       ('minference.ops', MINFERENCE / 'minference/ops')]:
        package = types.ModuleType(name)
        package.__path__ = [str(path)]
        sys.modules[name] = package
    sys.modules['minference.cuda'] = cuda
    sparse = importlib.import_module('minference.ops.pit_sparse_flash_attention_v2')
    # Pin the published MInference fallback explicitly; optional serving wheels
    # can otherwise silently change the selected implementation in this venv.
    sparse.sparse_attn_func = None
    sparse.convert_vertical_slash_indexes_opt = None
    source = HERE / 'qwen_dual_chunk_flash_attn.py'
    tree = ast.parse(source.read_text())
    cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'DualChunkFlashAttentionImpl')
    names = ('_dual_chunk_flash_attn_prefill_func', '_merge_attn_outputs')
    selected = [x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name in names]
    selected += [x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == '_sum_all_diagonal_matrix']
    assert len(selected) == 3
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *selected], type_ignores=[])
    ns = dict(torch=torch, F=F)
    exec(compile(ast.fix_missing_locations(module), str(source), 'exec'), ns)
    return sparse, ns, ready


def kernel_mask(arrays, head, row, q, length):
    bc, bo, cc, ci = [arrays[f'h{head:02d}_{name}'] for name in ('bc', 'bo', 'cc', 'ci')]
    mask = np.zeros(length, dtype=bool)
    for start in bo[row, :int(bc[row])]:
        start = int(start)
        if start < length:
            mask[max(0, start):min(start + B, q + 1, length)] = True
    cols = ci[row, :int(cc[row])]
    assert np.all((cols >= 0) & (cols <= q)), (q, cols)
    mask[cols[cols < length].astype(np.int64)] = True
    return mask


class Recorder:
    def __init__(self, sparse, out):
        self.sparse, self.out = sparse, out
        self.enabled = False
        self.layer, self.head = None, None
        self.original = sparse._triton_mixed_sparse_attention
        sparse._triton_mixed_sparse_attention = self.kernel
        self.operator_checks = []

    def start(self, folder, history, suffix):
        self.folder, self.history, self.suffix = folder, history, suffix
        folder.mkdir(parents=True, exist_ok=True)
        self.records, self.enabled = [], True

    def before_layer(self, module, args):
        if self.enabled:
            self.layer = module.layer_idx
            self.arrays, self.seen = {}, []

    def after_layer(self, module, args, output):
        if self.enabled:
            assert self.seen == list(range(28)), self.seen
            assert torch.isfinite(output[0]).all()
            path = self.folder / f'layer-{self.layer + 1:02d}.npz'
            np.savez_compressed(path, **self.arrays)
            self.records.append(dict(layer_zero_based=self.layer, output_finite=True,
                native_sparse_calls=len(self.seen), q_heads=28, kv_heads=4,
                native_packed_indices_observed=True, query_range=[self.history, self.history+self.suffix],
                trace_file=str(path.relative_to(self.out)), trace_sha256=sha(path)))
            print('LAYER', self.layer + 1, 'native_heads', len(self.seen), flush=True)

    def kernel(self, q, k, v, seq, bc, bo, cc, ci, sm_scale, *args, **kw):
        # The same tensors are forwarded to the original published Triton kernel.
        out = self.original(q, k, v, seq, bc, bo, cc, ci, sm_scale, *args, **kw)
        if self.enabled:
            assert q.shape[:2] == (1, 1) and q.shape[2] == self.history+self.suffix
            lo, hi = self.history // B, (self.history+self.suffix) // B
            self.seen.append(self.head)
            for label, tensor in [('bc', bc), ('bo', bo), ('cc', cc), ('ci', ci)]:
                self.arrays[f'h{self.head:02d}_{label}'] = tensor[0, 0, lo:hi].detach().cpu().numpy()
            # Numerical reference for actual packed-mask attention, first head of first layer.
            if self.layer == 0 and self.head == 0:
                qs = [self.history, self.history+63, self.history+self.suffix-1]
                for qi in qs:
                    mask = kernel_mask(self.arrays, 0, (qi-self.history)//B, qi, q.shape[2])
                    mask_t = torch.from_numpy(mask).to(q.device)
                    scores = (q[0, 0, qi].float() @ k[0, 0].float().T) * sm_scale
                    reference = torch.softmax(scores.masked_fill(~mask_t, -torch.inf), -1) @ v[0, 0].float()
                    error = float((reference-out[0, 0, qi].float()).abs().max())
                    # Native kernel converts scaled Q to BF16 before dot products.
                    assert error <= .06 + .03*float(reference.abs().max()), error
                    self.operator_checks.append(dict(layer=1, head=0, query=qi,
                        max_abs_error=error, reference_max_abs=float(reference.abs().max())))
        return out

    def finish(self):
        self.enabled = False
        assert [r['layer_zero_based'] for r in self.records] == list(range(28))
        return self.records


class QwenSelector:
    original_max_position_embeddings = 262144
    sparse_attention_last_q = 64

    def __init__(self, sparse, native, recorder):
        self.sparse, self.recorder = sparse, recorder
        for name in ('_dual_chunk_flash_attn_prefill_func', '_merge_attn_outputs'):
            setattr(self, name, types.MethodType(native[name], self))
        ar = torch.arange(64)
        self.last_q_mask = ar[None, :, None] >= ar[None, None, :]

    def _do_flash_attn(self, q, k, v, *, softmax_scale, causal, stage,
                       vertical_indices, slash_indices, vertical_indices_count,
                       slash_indices_count, sparse_attn_enabled, **kw):
        assert stage == 'intra' and causal and sparse_attn_enabled and q.shape[1] == 1
        vi = vertical_indices[0, :int(vertical_indices_count[0])].reshape(1, 1, -1)
        si = slash_indices[0, :int(slash_indices_count[0])].reshape(1, 1, -1)
        result = self.sparse.vertical_slash_sparse_attention(
            q.transpose(0, 1).unsqueeze(0), k.transpose(0, 1).unsqueeze(0),
            v.transpose(0, 1).unsqueeze(0), vi, si)
        # There is exactly one DCA fragment; the original merge ignores its LSE.
        return result.squeeze(0).transpose(0, 1), None


def main():
    assert os.environ.get('SLURM_JOB_ID') and torch.cuda.device_count() == 2
    out = HERE / f'qwen-{os.environ["SLURM_JOB_ID"]}'
    assert not out.exists()
    out.mkdir()
    torch.manual_seed(20260921)
    torch.set_num_threads(8)
    sparse, native, build = bootstrap()
    recorder = Recorder(sparse, out)
    selector = QwenSelector(sparse, native, recorder)
    provenance = json.loads((HERE / 'Qwen2.5-7B-Instruct-1M-checkpoint-verification.json').read_text())
    assert provenance['status'] == 'verified'
    for name, record in provenance['files'].items():
        assert sha(CHECKPOINT/name) == record['sha256'], name
    placement = {'model.embed_tokens':'cuda:0', 'model.rotary_emb':'cuda:0',
                 'model.norm':'cuda:1', 'lm_head':'cuda:1'}
    placement.update({f'model.layers.{i}':f'cuda:{int(i>=14)}' for i in range(28)})
    env = dict(model='Qwen/Qwen2.5-7B-Instruct-1M', revision=provenance['revision'],
        checkpoint_provenance=provenance, host=platform.node(), slurm_job_id=os.environ['SLURM_JOB_ID'],
        gpu=gpu_snapshot(), device_map=placement, index_build=build,
        kernel_source_sha256=sha(sparse.__file__), selector_source_sha256=sha(HERE/'qwen_dual_chunk_flash_attn.py'),
        selector_source=json.loads((HERE/'qwen-backend-source.json').read_text()),
        capture_sha256=sha(__file__), torch_version=torch.__version__,
        implementation='Official Qwen selector AST unchanged; refined per-head budgets; MInference native CUDA indices and Triton attention; HF Qwen2 projections/RoPE; full 64K first DCA chunk only',
        kv_layout=dict(layers=28,kv_heads=4,q_heads=28,head_dim=128,block_tokens=64,block_bytes_layer=131072),
        sequence_tokens=M+N,history_tokens=M,window_queries=N,
        prefill_chunk_tokens=M+N,dca_chunk_size=262144,dca_local_size=8192,selector_last_queries=64,
        threshold=32768,logical_causality='Attention kernel is causal; native selector observes last 64 Queries in the Prefill chunk, not a causal future-window predictor')
    save(out/'measured-environment.json', env)
    model, loading = AutoModelForCausalLM.from_pretrained(CHECKPOINT, local_files_only=True,
        torch_dtype=torch.bfloat16, device_map=placement, attn_implementation='sdpa', output_loading_info=True)
    save(out/'measured-loading.json', loading)
    assert not any(loading.get(k) for k in ('missing_keys','unexpected_keys','mismatched_keys','error_msgs'))
    model.eval()
    config = json.loads((CHECKPOINT/'sparse_attention_config.json').read_text())
    assert len(config) == len(model.model.layers) == 28
    assert model.config.dual_chunk_attention_config['chunk_size'] - model.config.dual_chunk_attention_config['local_size'] > M+N

    def attention(self, hidden_states, position_embeddings, attention_mask, past_key_value=None, **kwargs):
        assert past_key_value is None
        b, length, _ = hidden_states.shape
        assert b == 1 and 32768 < length <= 65536
        with torch.cuda.device(hidden_states.device):
            q = self.q_proj(hidden_states).view(b,length,28,128).transpose(1,2)
            k = self.k_proj(hidden_states).view(b,length,4,128).transpose(1,2)
            v = self.v_proj(hidden_states).view(b,length,4,128).transpose(1,2)
            q, k = apply_rotary_pos_emb(q,k,*position_embeddings)
            result = torch.empty_like(q)
            for head in range(28):
                recorder.head = head
                pattern, vi, si, _ = config[self.layer_idx][str(head)]
                assert pattern == 'vertical_and_slash'
                vi += 100 if vi == 30 else 0  # Official Qwen backend budget rule.
                qs, ks, vs = q[0,head].unsqueeze(1), k[0,head//7].unsqueeze(1), v[0,head//7].unsqueeze(1)
                value = selector._dual_chunk_flash_attn_prefill_func(qs,qs,qs,qs,qs,ks,vs,
                    None,128**-.5,262144,8192,[length],1.0,length,sparse_attn_enabled=True,
                    heads_vertical_size=torch.tensor([vi],dtype=torch.int32),
                    heads_slash_size=torch.tensor([si],dtype=torch.int32),group_size=1)
                result[0,head] = value[:,0]
            result = result.transpose(1,2).contiguous().view(b,length,-1)
            return self.o_proj(result), None

    for layer in model.model.layers:
        layer.self_attn.forward = types.MethodType(attention, layer.self_attn)
        layer.self_attn.register_forward_pre_hook(recorder.before_layer)
        layer.self_attn.register_forward_hook(recorder.after_layer)
    tokenizer = AutoTokenizer.from_pretrained(CHECKPOINT, local_files_only=True)
    inputs = {book:tokenizer((HERE/'texts'/f'{book}.txt').read_text(),add_special_tokens=True)['input_ids'] for book in BOOKS}
    assert all(len(ids) >= M+N for ids in inputs.values())
    print('MODEL_LOADED',sum(p.numel() for p in model.parameters()),flush=True)

    def forward(ids):
        tensor = torch.tensor([ids],device='cuda:0')
        with torch.inference_mode():
            outp = model(input_ids=tensor,use_cache=False,logits_to_keep=1)
        return outp.logits.detach().float().cpu()

    baseline = forward(inputs[BOOKS[0]][:33024])
    recorder.start(out/'validation',32512,512)
    measured = forward(inputs[BOOKS[0]][:33024])
    records = recorder.finish()
    error = float((baseline-measured).abs().max())
    assert error == 0 and torch.isfinite(measured).all()
    save(out/'measured-observer-validation.json',dict(paired_forward_max_abs_logit_diff=error,
        input_tokens=33024,layers=records,packed_kernel_reference=recorder.operator_checks))
    print('OBSERVER_VALIDATED',error,flush=True)
    for book, ids in inputs.items():
        folder = out/'traces'/f'pg19-{book}-M{M}-N{N}'
        recorder.start(folder,M,N)
        np.save(folder/'input_ids.npy',np.asarray(ids[:M+N],dtype=np.int32))
        for device in range(2):torch.cuda.reset_peak_memory_stats(device)
        before = gpu_snapshot()
        start = time.monotonic()
        logits = forward(ids[:M+N])
        layers = recorder.finish()
        assert torch.isfinite(logits).all()
        np.save(folder/'last_logits.npy',logits.numpy())
        save(folder/'run.json',dict(status='complete',model=env['model'],book_id=book,M=M,N=N,
            logits_finite=True,input_text_sha256=sha(HERE/'texts'/f'{book}.txt'),
            input_ids_sha256=sha(folder/'input_ids.npy'),layers=layers,
            input_source=f'https://storage.googleapis.com/deepmind-gutenberg/test/{book}.txt',
            instrumented_wall_seconds_not_latency_benchmark=time.monotonic()-start,
            peak_cuda_allocated_bytes_by_device=[torch.cuda.max_memory_allocated(i) for i in range(2)],
            gpu_before=before,gpu_after=gpu_snapshot()))
        save(out/'packed-kernel-reference.json',recorder.operator_checks)
        print('RUN_COMPLETE',book,flush=True)
    print('CAMPAIGN_COMPLETE',flush=True)


if __name__ == '__main__':
    main()
