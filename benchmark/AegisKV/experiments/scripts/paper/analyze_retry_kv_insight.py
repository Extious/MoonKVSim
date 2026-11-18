"""Forecast a retry tail's historical KV demand from strictly earlier queries.

Trace-derived retrospective evaluation, not a fault-injected execution.
Native captures use PG19 text and real model weights. They are not agentic traces.
"""
from pathlib import Path
import csv
import hashlib
import json
import numpy as np

ROOT=Path(__file__).resolve().parents[5]
BASE=ROOT/'benchmark/AegisKV/experiments/native-sparse'
OUT=ROOT/'benchmark/AegisKV/experiments/data/design-insights'
MODELS={'NOSA-1B':('20260914',28),'NOSA-3B':('20260915-nosa-3b',32),
        'MiniCPM4-8B':('20260915',32),'SeerAttention-Qwen3-8B':('20260918-seer-qwen3',36)}
M,N,PAST,TAIL,BLOCK=32768,512,512,64,64


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def counts(selected,lo,hi,b):
    x=selected[:,lo:hi];v=x[(x>=0)&(x<b)]
    return np.bincount(v,minlength=b)


def trace_counts(trace, record, cfg, lo, hi, b):
    if record.get('trace_format') == 'query_head_query_block_key_block_bool':
        # SeerAttention shares a native gate mask across each 64-query block.
        # Preserve its query-block semantics; do not invent per-query indices.
        qblock=cfg['query_block_size']
        assert lo % qblock == hi % qblock == 0
        assert cfg['block_size'] == BLOCK and record['native_mask_identity_verified']
        mask=trace['block_mask']
        assert mask.dtype == np.bool_ and mask.shape[-1] == (M+N)//BLOCK
        return mask[:,lo//qblock:hi//qblock,:b].sum(axis=(0,1),dtype=np.int64)*qblock
    return counts(trace['selected_blocks'],lo,hi,b)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    rows=[]; sources={}; per_layer=[]
    for model,(folder,layers) in MODELS.items():
        root=BASE/folder
        env_path=root/'measured-environment.json';env=json.loads(env_path.read_text())
        cfg=env['native_layer_config'];sources[str(env_path.relative_to(ROOT))]=sha(env_path)
        b=M//BLOCK
        # Sink plus the last full local window of history; keep this same deterministic
        # coverage in both policies, within their equal total byte budget.
        mandatory=np.unique(np.r_[np.arange(cfg['init_blocks']),np.arange(b-cfg['local_blocks'],b)])
        for book in ['10146','10321','10356']:
            runpath=root/'traces'/f'pg19-{book}-M{M}-N{N}'/'run.json'
            run=json.loads(runpath.read_text());assert run['status']=='complete' and run['logits_finite']
            assert (run['M'],run['N'])==(M,N) and len(run['layers'])==layers
            sources[str(runpath.relative_to(ROOT))]=sha(runpath)
            totals={}
            for record in run['layers']:
                path=root/record['trace_file'];assert sha(path)==record['trace_sha256']
                sources[str(path.relative_to(ROOT))]=record['trace_sha256']
                with np.load(path) as f:trace={key:f[key] for key in f.files}
                past=trace_counts(trace,record,cfg,M-PAST,M,b)
                needed=trace_counts(trace,record,cfg,M,M+TAIL,b)>0
                hot=np.lexsort((-np.arange(b),-past));recent=np.arange(b)[::-1]
                order={name:np.r_[mandatory,[i for i in arr if i not in set(mandatory)]]
                       for name,arr in [('past_frequency',hot),('recent_first',recent)]}
                for fraction in [.1,.2,.3,.4,.5,.6,.8,1.]:
                    k=int(np.ceil(fraction*b));assert k>=len(mandatory)
                    total=totals.setdefault(fraction,dict(needed=0,past_frequency=0,recent_first=0,oracle=0))
                    total['needed']+=int(needed.sum());total['oracle']+=min(k,int(needed.sum()))
                    for method,o in order.items():
                        hit=int(needed[o[:k]].sum()); total[method]+=hit
                        per_layer.append(dict(model=model,book_id=book,layer=record['layer_zero_based']+1,
                                              budget_fraction=fraction,method=method,selected_blocks=k,
                                              mandatory_blocks=len(mandatory),needed_blocks=int(needed.sum()),covered_blocks=hit))
            for fraction,t in totals.items():
                rows.append(dict(model=model,book_id=book,budget_fraction=fraction,
                                 needed_fraction=t['needed']/(layers*b),
                                 **{method:t[method]/t['needed'] for method in ['past_frequency','recent_first','oracle']}))
            print(model,book,'done',flush=True)
    for name,data in [('retry-kv-documents.csv',rows),('retry-kv-layers.csv',per_layer)]:
        with (OUT/name).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    summary={model:{method:dict(mean=float(np.mean([r[method] for r in rows if r['model']==model and r['budget_fraction']==.4])),
                                min=float(min(r[method] for r in rows if r['model']==model and r['budget_fraction']==.4)),
                                max=float(max(r[method] for r in rows if r['model']==model and r['budget_fraction']==.4)))
                    for method in ['past_frequency','recent_first','oracle','needed_fraction']} for model in MODELS}
    metadata=dict(evidence='Trace-derived causal prediction of a hypothetical retry tail; native weighted-model PG19 forwards, not a physical fault/retry test.',
                  history_tokens=M,prediction_queries_one_based=[M-PAST+1,M],retry_queries_one_based=[M+1,M+TAIL],
                  history_object='(layer, 64-token block), all KV heads',denominator='Distinct needed historical layer/block objects; repeated reads count once.',
                  source_models=list(MODELS),independent_documents_per_model=3,physical_capture_per_model_document=1,
                  main_figure_models=['NOSA-3B','MiniCPM4-8B','SeerAttention-Qwen3-8B'],
                  retained_archive_models=['NOSA-1B'],
                  selection_units='NOSA/MiniCPM4: per-query KV-group indices. SeerAttention: native 64-query/64-key block masks per query head; each block mask counts for its 64 queries, all KV heads share the physical placement object.',
                  seer_configuration='Qwen3-8B plus jiwonsong experimental SeerAttention Prefill gates; threshold .001 and checkpoint YaRN settings retained, optional last-two-query-block dense override disabled. Native block-sparse backend, no fixed sink/local blocks; past and target boundaries align to query blocks.',
                  statistic='For each document sum covered/needed objects over all layers, then mean across the three documents; whiskers are document min/max, not a confidence interval.',
                  mandatory_policy='Both methods reserve the sink and last full local window within the equal per-layer budget; no tail selection enters the ranking.',
                  interpretation='Original causal selections define retry demand if model, prefix state, committed tokens and selection semantics are preserved. Auxiliary selector state and prediction misses still require recovery.',
                  displayed_budget_fraction=.4,summary=summary,source_sha256=sources)
    (OUT/'retry-kv-summary.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':main()
