"""CPU-only, per-model maximum contexts and sequential chunked recovery.

Uses the frozen architecture estimator's exact SDK calls and state accounting.
Qwen 2507 beyond 256K is a full-attention cost projection: DCA is not modeled.
"""
from pathlib import Path
import csv
import importlib.util
import json
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
FROZEN = HERE.parent / 'reuse-aiconfigurator-architecture-h100'
spec = importlib.util.spec_from_file_location('architecture_estimator', FROZEN/'estimate_reuse.py')
sdk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdk)
reference = json.loads((FROZEN/'estimates.json').read_text())
for path, digest in reference['source_sha256'].items():
    assert sdk.sha(path) == digest, path

TAIL = 64
CHUNK = 8192
LIMITS = {'Qwen3-14B': 131072, 'Llama-3.1-70B': 131072,
          'Qwen3-235B-A22B-Instruct-2507': 1010000, 'DeepSeek-V3.2': 163840}
qwen = sdk.MODELS.pop('Qwen3-235B-A22B')
sdk.MODELS = {'Qwen3-14B': sdk.MODELS['Qwen3-14B'],
              'Llama-3.1-70B': sdk.MODELS['Llama-3.1-70B'],
              'Qwen3-235B-A22B-Instruct-2507': qwen,
              'DeepSeek-V3.2': sdk.MODELS['DeepSeek-V3.2']}
sdk.HERE = HERE
RAW = {}


def query(name, total, prefix):
    key = f'{name}:{total}:{prefix}'
    if key not in RAW:
        RAW[key] = sdk.estimate(name, total-TAIL, prefix)
    return key, RAW[key]


def main():
    models = {name: dict(**sdk.state_layout(name), context_limit=limit)
              for name, limit in LIMITS.items()}
    rows = []
    for name, model in models.items():
        limit = model['context_limit']
        totals = sorted({n for n in [8192,16384,32768,65536,131072,262144,524288,786432,limit] if n <= limit})
        for total in totals:
            history = total-TAIL
            hkey, hbm = query(name, total, history)
            chunks = []
            for prefix in range(0, total, CHUNK):
                end = min(prefix+CHUNK, total)
                key, result = query(name, end, prefix)
                # Vocabulary projection does not build KV. Exclude it for
                # every chunk and the HBM tail, including models whose SDK
                # context operation list does not include logits at all.
                excluded = {
                    k:v for k,v in result['ops_ms'].items() if 'logits_gemm' in k}
                chunks.append(dict(query=key, prefix_tokens=prefix, end_tokens=end,
                                   excluded_ops_ms=excluded,
                                   latency_ms=result['latency_ms']-sum(excluded.values())))
            h2d = history*model['layout']['bytes_per_token_per_rank']/64e9*1000
            hbm_excluded = {k:v for k,v in hbm['ops_ms'].items() if 'logits_gemm' in k}
            hbm_ms = hbm['latency_ms']-sum(hbm_excluded.values())
            peak = max(RAW[c['query']]['memory']['total'] for c in chunks)
            warnings = [dict(query=c['query'], warning=RAW[c['query']]['warning'])
                        for c in chunks if RAW[c['query']]['warning']]
            row = dict(model=name, total_tokens=total, context_tokens=history, tail_tokens=TAIL,
                       context_limit=limit, is_maximum=total==limit,
                       hbm_ms=hbm_ms, dram_ms=hbm_ms+h2d,
                       recompute_ms=sum(c['latency_ms'] for c in chunks), h2d_ms=h2d,
                       transferred_bytes_per_rank=history*model['layout']['bytes_per_token_per_rank'],
                       hbm_query=hkey, hbm_excluded_ops_ms=hbm_excluded,
                       recompute_chunks=chunks, recompute_peak_gib=peak,
                       warnings=warnings, hbm_warning=hbm['warning'],
                       status='memory_warning' if warnings or hbm['warning'] else 'estimated',
                       exceeds_config_context=total>model['config']['max_position_embeddings'],
                       dsa_beyond_table_context=name=='DeepSeek-V3.2' and total>32768,
                       qwen_full_attention_projection='2507' in name and total>262144)
            assert not row['exceeds_config_context']
            rows.append(row)
            print(name, total, row['status'], 'ms', *[round(row[k],3) for k in ['hbm_ms','dram_ms','recompute_ms']], 'peakGiB',round(peak,3),flush=True)
            # Preserve results and capacity warnings even if later work fails.
            (HERE/'partial-results.json').write_text(json.dumps(dict(rows=rows,queries=RAW),indent=2)+'\n')
    sources = dict(reference['source_sha256'])
    sources[str(FROZEN/'estimates.json')] = sdk.sha(FROZEN/'estimates.json')
    sources.update({str(p):sdk.sha(p) for p in [Path(__file__), *sorted((HERE/'configs').rglob('*.json')), *sorted((HERE/'official').rglob('*'))] if p.is_file()})
    out = dict(evidence='CPU static estimates and analytical transfer; no hardware measurements',
               created_at=datetime.now(timezone.utc).isoformat(), tool=reference['tool'],
               protocol=dict(reference['protocol'],
                   history_tokens='M=C-64; C is the plotted total context length',
                   total_context_limits=LIMITS, chunk_tokens=CHUNK,
                   recompute='sequential chunks of at most 8192 tokens from empty state; all previous chunks cached; vocabulary projection excluded',
                   endpoint='history and known 64-token tail rebuilt; vocabulary projection excluded in all paths',
                   long_qwen='Qwen3-235B-A22B-Instruct-2507; >256K uses full-attention cost projection, no DCA positional or sparse-kernel performance model',
                   context_limits='Qwen14 official YaRN 128K; Llama70 config 128K; DeepSeek official config 160K; Qwen2507 official extended config 1,010,000',
                   limitations=reference['protocol']['limitations']+[
                       'Qwen beyond 256K projects standard full-attention costs, not DCA sparse-kernel latency',
                       'chunk sums omit scheduler and inter-chunk CPU overhead; SDK memory includes one output-token reservation',
                       'maximum context is a source/configuration boundary, not an accuracy or deployment validation']),
               models=models,rows=rows,queries=RAW,source_sha256=sources)
    (HERE/'estimates.json').write_text(json.dumps(out,indent=2)+'\n')
    keys=['model','total_tokens','context_tokens','tail_tokens','context_limit','is_maximum',
          'hbm_ms','dram_ms','recompute_ms','h2d_ms','transferred_bytes_per_rank','recompute_peak_gib',
          'exceeds_config_context','dsa_beyond_table_context','qwen_full_attention_projection','status']
    with (HERE/'estimates.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore');w.writeheader();w.writerows(rows)
    print('completed',len(rows),'shapes',len(RAW),'unique SDK queries',flush=True)


if __name__ == '__main__':
    main()
