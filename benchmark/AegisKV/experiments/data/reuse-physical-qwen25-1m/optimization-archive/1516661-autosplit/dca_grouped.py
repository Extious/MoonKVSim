"""Explicit, instance-local optimization of the pinned dense DCA backend.

Keeps DCA position/scaling/chunk/merge semantics. Groups GQA heads, fixes the
multi-head LSE layout and optionally enables split-KV for short queries. Does
not change installed SGLang files or the sparse attention path.
"""
import hashlib
import inspect
from pathlib import Path

EXPECTED_SOURCE = "86fc86a8b2544a22294a3449c39bab689760239326ddbb8be4a95c3d577f18b7"


def optimized_class(native_class):
    import torch
    module = inspect.getmodule(native_class)
    assert hashlib.sha256(Path(inspect.getfile(native_class)).read_bytes()).hexdigest() == EXPECTED_SOURCE

    class GroupedDCA(native_class):
        def _dual_chunk_flash_attn_prefill(
            self, q, q_succ, q_inter, q_succ_critical, q_inter_critical,
            k, v, cu_seqlens_q, cu_seqlens_k, orig_seq_lens,
            scaling_factor, softmax_scale, causal=True, window_size=(-1, -1),
            block_table=None, chunk_size=8192, local_size=1024,
        ):
            assert causal and window_size == (-1, -1)
            assert not self.sparse_attention_enabled, "Optimization is dense DCA only"
            qs, ks = cu_seqlens_q.cpu().tolist(), cu_seqlens_k.cpu().tolist()
            outputs = []
            for i in range(len(qs)-1):
                start, end = qs[i:i+2]
                if start == end:
                    continue
                key = k if block_table is not None else k[ks[i]:ks[i+1]]
                value = v if block_table is not None else v[ks[i]:ks[i+1]]
                if not key.shape[0]:
                    outputs.append(torch.zeros_like(q[start:end]))
                    continue
                assert q.shape[-2] % key.shape[-2] == 0
                outputs.append(self._dual_chunk_flash_attn_prefill_func(
                    q[start:end], q_succ[start:end], q_inter[start:end],
                    q_succ_critical[start:end], q_inter_critical[start:end],
                    key, value, None if block_table is None else block_table[i],
                    softmax_scale, chunk_size, local_size,
                    scaling_factor[i].item(), ks[i+1]-ks[i],
                    sparse_attn_enabled=False, group_size=q.shape[-2]//key.shape[-2]))
            return torch.cat(outputs, dim=0)

        def _do_flash_attn(
            self, query_states, key_states, value_states, softmax_scale,
            causal=True, max_seqlen_k=None, stage="intra",
            vertical_indices=None, slash_indices=None,
            vertical_indices_count=None, slash_indices_count=None,
            mergehead_softmax_scale=None, sparse_attn_enabled=False,
        ):
            assert not sparse_attn_enabled
            nq, nh = query_states.shape[:2]
            nk = key_states.shape[0] if max_seqlen_k is None else max_seqlen_k
            splits = self.aegis_short_splits if nq <= 64 else 1
            output, lse, *_ = module.flash_attn_varlen_func(
                q=query_states, k=key_states, v=value_states,
                softmax_scale=softmax_scale,
                cu_seqlens_q=torch.tensor([0,nq],dtype=torch.int32,device=query_states.device),
                cu_seqlens_k=torch.tensor([0,nk],dtype=torch.int32,device=query_states.device),
                max_seqlen_q=nq, max_seqlen_k=nk, causal=causal,
                num_splits=splits, return_softmax_lse=True)
            # FA returns [heads, queries]; native single-head reshape is not
            # valid once multiple heads enter the same DCA merge operation.
            assert lse.numel() == nh*nq
            return output, lse.reshape(nh,nq).unsqueeze(0).float()

    return GroupedDCA


def install(backend, short_splits=0):
    assert short_splits in (0,1,8,32)
    native = type(backend)
    backend.__class__ = optimized_class(native)
    backend.aegis_short_splits = short_splits
    return native


def set_variant(backend, native, grouped, use_grouped):
    backend.__class__ = grouped if use_grouped else native
