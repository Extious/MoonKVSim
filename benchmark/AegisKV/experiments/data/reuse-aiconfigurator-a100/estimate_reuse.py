"""Deterministic recovery estimates, not GPU measurements.

Run with /home/comp/zhanzhao/aiconfigurator/.venv/bin/python.
All paths end after the same known 64-token tail's forward pass. HBM uses
the SDK's prefix=M argument, while Recompute uses prefix=0 for M+64 tokens.
DRAM adds a serialized full-history H2D model, using the PCIe bandwidth in
the pinned AIConfigurator system YAML. No repetition/CI is meaningful here.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/aegiskv-motivation-mpl")
from aiconfigurator.cli.api import cli_estimate
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
AIC = Path('/home/comp/zhanzhao/aiconfigurator')
SYSTEM = AIC/'src/aiconfigurator/systems/a100_sxm.yaml'
MODELS = ['Qwen3-4B', 'Qwen3-8B', 'Qwen3-14B']
CONTEXTS = [8192, 16384, 32768, 65536, 131072]
TAIL = 64


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def estimate(model, history, prefix):
    result = cli_estimate(
        str(HERE/'configs'/model), 'a100_sxm', mode='static_ctx',
        backend_name='vllm', backend_version='0.14.0', database_mode='HYBRID',
        isl=history+TAIL, prefix=prefix, osl=1, batch_size=1,
        tp_size=1, pp_size=1, gemm_quant_mode='bfloat16',
        kvcache_quant_mode='bfloat16', fmha_quant_mode='bfloat16')
    ops = result.summary.get_context_latency_dict()
    # The API result table rounds TTFT to three decimal places; retain the op sum.
    assert abs(sum(ops.values())-result.ttft) <= 0.000501
    return dict(latency_ms=sum(ops.values()), reported_ttft_ms=result.ttft, ops_ms=ops,
                op_sources=result.summary.get_context_source_dict(),
                memory=result.summary.get_memory(), warning=result.kv_cache_warning,
                args=dict(isl=history+TAIL, prefix=prefix, osl=1, mode='static_ctx'))


def main():
    system = yaml.safe_load(SYSTEM.read_text())
    bandwidth = system['node']['pcie_bw']
    sources = [SYSTEM, Path(__file__), HERE/'configs/PROVENANCE.json']
    # Pin the local code and all tables that the selected backend may query.
    sources += sorted((AIC/'src/aiconfigurator/sdk').rglob('*.py'))
    sources += [AIC/'src/aiconfigurator/cli/api.py']
    sources += [p for p in (AIC/'src/aiconfigurator/systems/data/a100_sxm').rglob('*')
                if p.is_file() and ('vllm' in str(p) or p.suffix in ('.yaml','.json'))]
    out = dict(evidence='static estimates; no physical recovery measurements',
        created_at=datetime.now(timezone.utc).isoformat(), script_sha256=sha(__file__),
        tool=dict(version='0.9.0', commit=subprocess.check_output(
            ['git','-C',str(AIC),'rev-parse','HEAD'],text=True).strip(),
            system='a100_sxm',backend='vllm',backend_version='0.14.0',database_mode='HYBRID'),
        protocol=dict(history_tokens=CONTEXTS,tail_tokens=TAIL,batch_size=1,tp=1,pp=1,
            weights='BF16',kv='BF16',attention='dense GQA',
            endpoint='all M+64 KV available after forward; excludes sampled-token decode',
            hbm='entire M-token KV resident at the actual takeover GPU; tail prefill',
            dram='host-local full-history copy then identical tail prefill; no overlap',
            recompute='one empty-cache forward over M+64 tokens',
            h2d_bandwidth_bytes_per_s=bandwidth,bandwidth_evidence='system YAML assumption, not measured',
            transfer_formula='2 * layers * kv_heads * head_dim * 2 * M / pcie_bw',
            excluded=['failure detection','queueing','model loading','pre-failure replication',
                      'software cache binding','allocator and DMA setup','transfer contention'],
            statistics='deterministic shapes, no input workloads, repetitions, or confidence intervals',
            context_boundary='Performance shape estimates beyond model config max_position_embeddings=40960; '
                'not accuracy validation or proof of deployable long-context support.',
            unsupported_native_models=['MiniCPM4-8B','NOSA-1B','NOSA-3B']),
        models={},rows=[],source_sha256={})
    for name in MODELS:
        config_path=HERE/'configs'/name/'config.json'; sources.append(config_path)
        cfg=json.loads(config_path.read_text())
        bytes_per_token=2*cfg['num_hidden_layers']*cfg['num_key_value_heads']*cfg['head_dim']*2
        out['models'][name]=dict(config=cfg,kv_bytes_per_token=bytes_per_token)
        for history in CONTEXTS:
            hbm=estimate(name,history,history); recompute=estimate(name,history,0)
            transfer_ms=bytes_per_token*history/bandwidth*1000
            row=dict(model=name,context_tokens=history,tail_tokens=TAIL,
                hbm_ms=hbm['latency_ms'],dram_ms=hbm['latency_ms']+transfer_ms,
                recompute_ms=recompute['latency_ms'],h2d_ms=transfer_ms,
                transferred_bytes=bytes_per_token*history,
                status='estimated' if not (hbm['warning'] or recompute['warning']) else 'memory_warning',
                hbm_details=hbm,recompute_details=recompute)
            out['rows'].append(row)
            print(name,history,row['status'],*[round(row[k],3) for k in ('hbm_ms','dram_ms','recompute_ms')],flush=True)
    # Candidate branch costs use exact prefix lengths, without interpolation or extrapolating a plotted curve.
    selection=ROOT/'benchmark/AegisKV/experiments/data/motivation-wide-cc/wide-example-failure-position.csv'
    if selection.exists():
        sources.append(selection)
        out['workflow_costs']=[]
        for r in csv.DictReader(selection.open()):
            p=int(r['prefix_tokens'])
            e=estimate('Qwen3-14B',p,0)
            out['workflow_costs'].append(dict(branch_index=int(r['branch_index']),prefix_tokens=p,
                recompute_s=e['latency_ms']/1000,details=e))
    out['source_sha256']={str(p):sha(p) for p in sources}
    (HERE/'estimates.json').write_text(json.dumps(out,indent=2,default=float)+'\n')
    keys=['model','context_tokens','tail_tokens','hbm_ms','dram_ms','recompute_ms','h2d_ms','transferred_bytes','status']
    with (HERE/'estimates.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=keys,extrasaction='ignore');writer.writeheader();writer.writerows(out['rows'])


if __name__=='__main__':
    main()
