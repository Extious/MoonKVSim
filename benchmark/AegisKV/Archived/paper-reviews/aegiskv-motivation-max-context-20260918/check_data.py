from pathlib import Path
import csv
import hashlib
import json
import math

ROOT = Path('/home/comp/zhanzhao/MoonKVSim')
HERE = Path(__file__).resolve().parent
DATA = ROOT/'benchmark/AegisKV/experiments/data/reuse-aiconfigurator-max-context-h100'
d = json.loads((DATA/'estimates.json').read_text())
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
for p,h in d['source_sha256'].items():
    assert sha(p)==h,p
for p,h in json.loads((HERE/'protected-hashes.json').read_text()).items():
    assert sha(p)==h,p
assert len(d['rows'])==25 and len(d['queries'])==201
for r in d['rows']:
    name=r['model']; model=d['models'][name]; c=r['total_tokens']; m=r['context_tokens']
    assert c==m+64 and c<=model['context_limit']==r['context_limit']
    assert r['is_maximum']==(c==model['context_limit'])
    assert not r['exceeds_config_context'] and r['status']=='estimated'
    assert not r['hbm_warning'] and not r['warnings']
    cfg=model['config']; layers=cfg['num_hidden_layers']
    if name=='DeepSeek-V3.2':
        bpt=layers*(cfg['kv_lora_rank']*2+cfg['qk_rope_head_dim']*2+cfg['index_head_dim']+4*math.ceil(cfg['index_head_dim']/128))
    else:
        dim=cfg.get('head_dim',cfg['hidden_size']//cfg['num_attention_heads'])
        bpt=layers*2*math.ceil(cfg['num_key_value_heads']/model['tp'])*dim*2
    assert bpt==model['layout']['bytes_per_token_per_rank']
    assert r['transferred_bytes_per_rank']==m*bpt
    assert math.isclose(r['h2d_ms'],m*bpt/64e9*1000)
    assert math.isclose(r['dram_ms'],r['hbm_ms']+r['h2d_ms'])
    h=d['queries'][r['hbm_query']]
    assert h['args']['isl']==c and h['args']['prefix']==m
    assert r['hbm_excluded_ops_ms']=={k:v for k,v in h['ops_ms'].items() if 'logits_gemm' in k}
    assert math.isclose(r['hbm_ms'],h['latency_ms']-sum(r['hbm_excluded_ops_ms'].values()))
    end=0; latency=0; peak=0
    for ch in r['recompute_chunks']:
        q=d['queries'][ch['query']]
        assert ch['prefix_tokens']==end and q['args']['prefix']==end
        end=ch['end_tokens'];assert q['args']['isl']==end
        assert 0<end-ch['prefix_tokens']<=8192
        excluded={k:v for k,v in q['ops_ms'].items() if 'logits_gemm' in k}
        assert ch['excluded_ops_ms']==excluded
        assert math.isclose(ch['latency_ms'],sum(q['ops_ms'].values())-sum(excluded.values()))
        latency+=ch['latency_ms'];peak=max(peak,q['memory']['total'])
    assert end==c
    assert math.isclose(latency,r['recompute_ms']) and math.isclose(peak,r['recompute_peak_gib'])
    assert r['qwen_full_attention_projection']==('2507' in name and c>262144)
    assert r['dsa_beyond_table_context']==(name=='DeepSeek-V3.2' and c>32768)
for name,model in d['models'].items():
    rows=[r for r in d['rows'] if r['model']==name]
    assert max(r['total_tokens'] for r in rows)==model['context_limit']
for q in d['queries'].values():
    assert not q['warning'] and q['memory']['total']<=80
    assert math.isclose(q['latency_ms'],sum(q['ops_ms'].values()))
    assert all(math.isfinite(v) and v>=0 for v in q['ops_ms'].values())
with (DATA/'estimates.csv').open() as f:
    rows=list(csv.DictReader(f))
assert len(rows)==25
for a,b in zip(rows,d['rows']):
    assert a['model']==b['model'] and int(a['total_tokens'])==b['total_tokens']
    for key in ['hbm_ms','dram_ms','recompute_ms']:assert float(a[key])==b[key]
checks=dict(shapes=25,path_values=75,unique_sdk_queries=201,
            all_source_hashes_match=True,protected_figure1_design_and_old_matrix_unchanged=True,
            exact_maxima_and_tail_accounting=True,full_state_bytes_verified=True,
            continuous_chunk_prefixes_verified=True,vocabulary_projection_excluded_from_all_paths=True,
            latency_sums_and_csv_match=True,all_queries_pass_static_memory=True,
            maximum_estimated_gib=max(q['memory']['total'] for q in d['queries'].values()),
            extrapolation_flags_verified=True,physical_experiments=False)
(HERE/'data-checks.json').write_text(json.dumps(checks,indent=2)+'\n')
print(json.dumps(checks,indent=2))
