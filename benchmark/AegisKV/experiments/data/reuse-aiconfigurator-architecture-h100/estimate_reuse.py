"""CPU-only AIConfigurator estimates across scale, MoE and sparse attention.

All three recovery paths share a model-specific TP configuration and M+64
completion endpoint. No GPU experiment or end-to-end recovery measurement.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault('HF_HUB_OFFLINE', '1')
from aiconfigurator.cli.api import cli_estimate, _build_model_config
from aiconfigurator.sdk.models import get_model
import yaml

HERE = Path(__file__).resolve().parent
AIC = Path('/home/comp/zhanzhao/aiconfigurator')
SYSTEM = 'h100_sxm'
BACKEND_VERSION = '0.19.0'
TAIL = 64
CONTEXTS = [8192, 16384, 32768, 65536, 131072]
MODELS = {
    'Qwen3-14B': dict(parameters_b=14, active_parameters_b=14, category='dense GQA',
                     tp=1, ep=1, moe_tp=1, is_moe=False),
    'Llama-3.1-70B': dict(parameters_b=70, active_parameters_b=70, category='dense GQA',
                        tp=4, ep=1, moe_tp=4, is_moe=False),
    'Qwen3-235B-A22B': dict(parameters_b=235, active_parameters_b=22, category='MoE + dense GQA',
                          tp=16, ep=16, moe_tp=1, is_moe=True),
    'DeepSeek-V3.2': dict(parameters_b=671, active_parameters_b=37, category='MoE + sparse DSA',
                         tp=32, ep=32, moe_tp=1, is_moe=True),
}


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def estimate(name, history, prefix):
    spec = MODELS[name]
    args = dict(mode='static_ctx', backend_name='vllm', backend_version=BACKEND_VERSION,
                database_mode='HYBRID', isl=history+TAIL, prefix=prefix, osl=1, batch_size=1,
                tp_size=spec['tp'], pp_size=1, attention_dp_size=1,
                gemm_quant_mode='bfloat16', kvcache_quant_mode='bfloat16',
                fmha_quant_mode='bfloat16', nextn=0)
    if spec['is_moe']:
        args.update(moe_tp_size=spec['moe_tp'], moe_ep_size=spec['ep'], moe_quant_mode='bfloat16')
    result = cli_estimate(str(HERE/'configs'/name), SYSTEM, **args)
    ops = result.summary.get_context_latency_dict()
    assert abs(sum(ops.values())-result.ttft) <= .000501
    return dict(latency_ms=sum(ops.values()), reported_ttft_ms=result.ttft, ops_ms=ops,
                op_sources=result.summary.get_context_source_dict(),
                memory=result.summary.get_memory(), warning=result.kv_cache_warning, args=args)


def state_layout(name):
    spec = MODELS[name]
    cfg = json.loads((HERE/'configs'/name/'config.json').read_text())
    layers = cfg['num_hidden_layers']
    if name == 'DeepSeek-V3.2':
        # MLA latent and RoPE keys are replicated across attention TP ranks.
        # DSA additionally needs the FP8 indexer key and its FP32 scale.
        kv_per_layer = cfg['kv_lora_rank']*2 + cfg['qk_rope_head_dim']*2
        index_per_layer = cfg['index_head_dim'] + math.ceil(cfg['index_head_dim']/128)*4
        layout = dict(kv_bytes_per_token_per_rank=layers*kv_per_layer,
                      auxiliary_bytes_per_token_per_rank=layers*index_per_layer,
                      formula='layers * (kv_lora_rank*2 + rope_dim*2 + index_dim + ceil(index_dim/128)*4)',
                      state='BF16 MLA latent + BF16 RoPE key + FP8 indexer key + FP32 scale; replicated per TP rank')
    else:
        head_dim = cfg.get('head_dim') or cfg['hidden_size']//cfg['num_attention_heads']
        local_kv_heads = math.ceil(cfg['num_key_value_heads']/spec['tp'])
        layout = dict(kv_bytes_per_token_per_rank=2*layers*local_kv_heads*head_dim*2,
                      auxiliary_bytes_per_token_per_rank=0,
                      formula='2 * layers * ceil(kv_heads/TP) * head_dim * 2',
                      state='BF16 GQA keys and values; KV heads replicated when TP exceeds KV-head count')
    layout['bytes_per_token_per_rank'] = (layout['kv_bytes_per_token_per_rank']
                                         + layout['auxiliary_bytes_per_token_per_rank'])
    mc = _build_model_config(spec['tp'], 1, 1, spec['moe_tp'], spec['ep'],
                             'bfloat16', 'bfloat16', 'bfloat16',
                             'bfloat16' if spec['is_moe'] else None, None)
    model = get_model(str(HERE/'configs'/name), mc, 'vllm')
    assert model.get_kvcache_bytes_per_sequence(1) == layout['bytes_per_token_per_rank']
    return dict(**spec, config=cfg, layout=layout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--capacity-check', action='store_true')
    args = parser.parse_args()
    system_file = AIC/'src/aiconfigurator/systems'/f'{SYSTEM}.yaml'
    bandwidth = yaml.safe_load(system_file.read_text())['node']['pcie_bw']
    models = {name: state_layout(name) for name in MODELS}
    rows = []
    for name, model in models.items():
        for history in ([CONTEXTS[-1]] if args.capacity_check else CONTEXTS):
            hbm = estimate(name, history, history)
            recompute = estimate(name, history, 0)
            state_bytes = model['layout']['bytes_per_token_per_rank']*history
            transfer_ms = state_bytes/bandwidth*1000
            row = dict(model=name, context_tokens=history, tail_tokens=TAIL,
                       hbm_ms=hbm['latency_ms'], dram_ms=hbm['latency_ms']+transfer_ms,
                       recompute_ms=recompute['latency_ms'], h2d_ms=transfer_ms,
                       transferred_bytes_per_rank=state_bytes,
                       transferred_bytes_all_ranks=state_bytes*model['tp'],
                       exceeds_config_context=history+TAIL>model['config']['max_position_embeddings'],
                       dsa_beyond_table_context=(name=='DeepSeek-V3.2' and history+TAIL>32768),
                       status='estimated' if not (hbm['warning'] or recompute['warning']) else 'memory_warning',
                       hbm_details=hbm, recompute_details=recompute)
            rows.append(row)
            print(name, history, row['status'], 'ms',
                  *[round(row[k],3) for k in ('hbm_ms','dram_ms','recompute_ms')],
                  'GiB',round(recompute['memory']['total'],3), flush=True)
    if args.capacity_check:
        (HERE/'capacity-check.json').write_text(json.dumps(rows,indent=2)+'\n')
        return
    sources = [Path(__file__), system_file, HERE/'configs/PROVENANCE.json']
    sources += list((HERE/'configs').rglob('config.json'))
    sources += sorted((AIC/'src/aiconfigurator/sdk').rglob('*.py'))
    sources += [AIC/'src/aiconfigurator/cli/api.py']
    sources += sorted(p for p in (AIC/'src/aiconfigurator/systems/data'/SYSTEM/'vllm'/BACKEND_VERSION).rglob('*') if p.is_file())
    out = dict(evidence='static estimates; no physical recovery measurements',
               created_at=datetime.now(timezone.utc).isoformat(),
               tool=dict(version='0.9.0', commit=subprocess.check_output(
                   ['git','-C',str(AIC),'rev-parse','HEAD'],text=True).strip(),
                   system=SYSTEM,backend='vllm',backend_version=BACKEND_VERSION,database_mode='HYBRID'),
               protocol=dict(history_tokens=CONTEXTS,tail_tokens=TAIL,batch_size=1,pp=1,
                   weights='BF16, explicitly overriding checkpoint quantization metadata',
                   kv='BF16; DSA indexer uses FP8 keys and FP32 scales',
                   endpoint='all history state and known 64-token tail state ready for continued decoding',
                   hbm='entire per-rank history and sparse auxiliary state resident in takeover TP group',
                   dram='all ranks restore their state concurrently, then the same tail forward; no transfer/compute overlap',
                   recompute='empty-cache forward over M+64 tokens; DSA uses ContextDSAModule, not dense proxy',
                   h2d_bandwidth_bytes_per_s_per_rank=bandwidth,
                   bandwidth_evidence='system YAML assumption, not measured; independent per-GPU links and unconstrained host bandwidth',
                   comparison='within-model three-path comparison; different TP/GPU allocations, not equal-resource model ranking',
                   excluded=['detection','queueing','weight loading','pre-failure replication','software binding','DMA setup','host/link contention'],
                   limitations=['no physical execution or accuracy validation','DSA module tables reach 32768 total tokens; beyond-table estimates are extrapolations',
                                'cached-tail DSA table timings use SDK analytical prefix correction',
                                'model configs and hardware/kernel tables are pinned; BF16 DeepSeek estimates are not execution of the native FP8 checkpoint',
                                'no sparse selected-token transfer or overlap assumed; DRAM restores full required historical state']),
               models=models,rows=rows,source_sha256={str(p):sha(p) for p in sources})
    (HERE/'estimates.json').write_text(json.dumps(out,indent=2)+'\n')
    keys=['model','context_tokens','tail_tokens','hbm_ms','dram_ms','recompute_ms','h2d_ms',
          'transferred_bytes_per_rank','transferred_bytes_all_ranks','exceeds_config_context','dsa_beyond_table_context','status']
    with (HERE/'estimates.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore');writer.writeheader();writer.writerows(rows)


if __name__=='__main__':
    main()
