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
MODELS={'NOSA-1B':('20260914',28),'NOSA-3B':('20260915-nosa-3b',32),'MiniCPM4-8B':('20260915',32)}
M,N,PAST,TAIL,BLOCK=32768,512,512,64,64


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def counts(selected,lo,hi,b):
    x=selected[:,lo:hi];v=x[(x>=0)&(x<b)]
    return np.bincount(v,minlength=b)


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
                with np.load(path) as f:s=f['selected_blocks']
                past=counts(s,M-PAST,M,b);needed=counts(s,M,M+TAIL,b)>0
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
                  statistic='For each document sum covered/needed objects over all layers, then mean across the three documents; whiskers are document min/max, not a confidence interval.',
                  mandatory_policy='Both methods reserve the sink and last full local window within the equal per-layer budget; no tail selection enters the ranking.',
                  interpretation='Original causal selections define retry demand if model, prefix state, committed tokens and selection semantics are preserved. Auxiliary selector state and prediction misses still require recovery.',
                  displayed_budget_fraction=.4,summary=summary,source_sha256=sources)
    (OUT/'retry-kv-summary.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':main()
