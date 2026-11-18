"""Load the publisher's Prefill model without importing unrelated backends.

Unused FlashAttention entry points are fail-closed guards, never replacements
for a calculation. Sparse kernels, gate scoring, RoPE, and normalization use
the publisher's unmodified code and explicit native configuration options.
"""
import importlib
import importlib.util
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent/'20260918-seer/qwen3-review/CompactAttention'
PAD_SOURCE = ROOT.parent/'runtime-20260914/upstream/source/NOSA-1cbee77d607f9051b206a09c862bea28becb9e67/dependencies/flash-attention-nosa/flash_attn_nosa/bert_padding.py'


def forbid(*args, **kwargs):
    raise AssertionError('Unexpected unused FlashAttention/dense backend; no substitution permitted')


def bootstrap():
    import torch
    import transformers  # Detect installed backends before adding import guards.
    package=types.ModuleType('compact_attn');package.__path__=[str(SOURCE/'compact_attn')]
    sys.modules['compact_attn']=package
    import flash_attn
    flash_attn.flash_attn_func=forbid
    flash_attn.flash_attn_varlen_func=forbid
    flash_attn.flash_attn_with_kvcache=forbid
    layers=types.ModuleType('flash_attn.layers');layers.__path__=[]
    rotary=types.ModuleType('flash_attn.layers.rotary');rotary.apply_rotary_emb_func=forbid
    sys.modules['flash_attn.layers']=layers;sys.modules['flash_attn.layers.rotary']=rotary
    spec=importlib.util.spec_from_file_location('flash_attn.bert_padding',PAD_SOURCE)
    padding=importlib.util.module_from_spec(spec);spec.loader.exec_module(padding)
    sys.modules['flash_attn.bert_padding']=padding
    model=importlib.import_module('compact_attn.prefill_sparse.qwen3.modeling_qwen3_seerattn')
    forward=importlib.import_module('compact_attn.modules.attention_forward')
    return model,forward


if __name__=='__main__':
    model,forward=bootstrap()
    print('NATIVE_QWEN3_PREFILL_IMPORT_OK',model.SeerAttnQwen3ForCausalLM.__name__)
