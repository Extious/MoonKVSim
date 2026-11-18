"""Workflow-disjoint runtime prediction from observed CC subagent episodes.

Only admission-visible metadata and already completed requests enter features.
Reported agent completion times and future outputs are evaluation labels only.
No hardware run or end-to-end recovery is performed by this analysis.
"""
from pathlib import Path
from collections import Counter, defaultdict
import argparse
import csv
import hashlib
import importlib.util
import json
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / 'benchmark/AegisKV/experiments/data/design-insights'
TRACE = Path('/home/comp/zhanzhao/sglsim/AegisKV/doc/Archived/2026-08-06-pre-kvcache-centric/presentations/presentation/experiments/sglsim_large/traces/cc-traces-weka-062126/traces.materialized.jsonl')
TRACE_SHA = '29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276'
SALT = 'aegiskv-design-insight-agent-20260918'


def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write_csv(path, rows):
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)


def extract(trace):
    digest = hashlib.sha256(); counts = Counter(); agents = []; roles = Counter()
    with trace.open('rb') as f:
        for line in f:
            digest.update(line)
            if not line.strip(): continue
            workflow = json.loads(line); counts['source_workflows'] += 1
            for index, g in enumerate(workflow['requests']):
                if g.get('type') != 'subagent': continue
                counts['source_agents'] += 1
                if g.get('status') != 'completed':
                    counts['excluded_not_completed'] += 1; continue
                dur = float(g.get('duration_ms') or 0)/1000
                raw = g.get('requests') or []
                if dur <= 0 or not raw:
                    counts['excluded_empty_or_nonpositive'] += 1; continue
                start = float(g['t']); end = start + dur
                reqs = [dict(t=float(r['t']), prompt=int(r.get('in') or 0),
                             output=int(r.get('out') or 0), latency=float(r.get('api_time') or 0),
                             model=str(r.get('model') or 'unknown')) for r in raw]
                reqs.sort(key=lambda r:r['t'])
                # Do not silently change reported wall-clock labels to fit inconsistent request clocks.
                if any(r['t'] < start-0.001 or r['t'] >= end or r['latency'] < 0 or
                       r['t']+r['latency'] > end+0.001 for r in reqs):
                    counts['excluded_inconsistent_episode_clock'] += 1; continue
                role=str(g.get('subagent_type') or 'unknown'); roles[role]+=1
                agents.append(dict(workflow_id=workflow['id'], agent_id=f"{index}:{g.get('agent_id','')}",
                                   role=role, start=start, duration_s=dur, requests=reqs))
            if counts['source_workflows'] % 100 == 0: print('extracted workflows',counts['source_workflows'],flush=True)
    assert digest.hexdigest()==TRACE_SHA, 'The CC source changed'
    counts['included_agents']=len(agents)
    counts['included_workflows']=len({a['workflow_id'] for a in agents})
    with (OUT/'agent-episodes.jsonl').open('w') as f:
        for a in agents:f.write(json.dumps(a,separators=(',',':'))+'\n')
    provenance=dict(source=str(trace),source_sha256=TRACE_SHA,counts=dict(counts),roles=dict(roles),
                    extraction='All completed subagent groups with positive durations, requests, and internally consistent clocks; no duration or error threshold.')
    (OUT/'agent-extraction.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print(json.dumps(provenance,indent=2),flush=True)


def analyze():
    agents=[json.loads(s) for s in (OUT/'agent-episodes.jsonl').read_text().splitlines()]
    roles=sorted({a['role'] for a in agents}); models=sorted({r['model'] for a in agents for r in a['requests']})
    rows=[]; features=[]
    for ai,a in enumerate(agents):
        reqs=a['requests']; dur=a['duration_s']
        fold=int.from_bytes(hashlib.sha256((SALT+':'+a['workflow_id']).encode()).digest()[:8],'big')%5
        for ri,r in enumerate(reqs):
            now=r['t']; elapsed=max(now-a['start'],0)
            completed=[p for p in reqs[:ri] if p['t']+p['latency'] <= now]
            visible=reqs[:ri+1]
            # Every input value is available by this request's arrival.
            numeric=[elapsed, r['prompt'],reqs[0]['prompt'],len(completed),ri+1,
                     sum(p['latency'] for p in completed),sum(p['output'] for p in completed),
                     sum(p['prompt'] for p in visible),max(p['prompt'] for p in visible),
                     completed[-1]['latency'] if completed else 0,
                     max(now-max((p['t']+p['latency'] for p in completed),default=now),0)]
            features.append([np.log1p(max(x,0)) for x in numeric]+
                            [float(a['role']==v) for v in roles]+[float(r['model']==v) for v in models])
            rows.append(dict(agent_index=ai,workflow_id=a['workflow_id'],agent_id=a['agent_id'],role=a['role'],
                             request_index=ri,fold=fold,elapsed_s=elapsed,total_duration_s=dur,
                             remaining_s=dur-elapsed,model=r['model']))
    x=np.asarray(features); y=np.asarray([r['remaining_s'] for r in rows]); fold=np.asarray([r['fold'] for r in rows])
    model_path=OUT/'provenance/aegis_gbdt.py'
    spec=importlib.util.spec_from_file_location('insight_gbdt',model_path)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    pred=np.zeros(len(rows)); baseline=np.zeros(len(rows)); med=np.zeros(len(rows))
    config=module.AegisGBDTConfig(estimators=80,learning_rate=.06,max_depth=3,min_leaf=32,max_bins=32)
    # A fixed diagnostic model, not a hyperparameter search over the held-out folds.
    fit_info=[]
    for k in range(5):
        train=fold!=k; test=fold==k
        fit=module.AegisGBDTRegressor(config).fit(x[train],y[train]); pred[test]=fit.predict(x[test])
        train_agents=[a for ai,a in enumerate(agents) if int.from_bytes(hashlib.sha256((SALT+':'+a['workflow_id']).encode()).digest()[:8],'big')%5 != k]
        global_d=[a['duration_s'] for a in train_agents]
        byrole=defaultdict(list)
        for a in train_agents: byrole[a['role']].append(a['duration_s'])
        for j in np.flatnonzero(test):
            r=rows[j]; vals=byrole.get(r['role'],global_d)
            baseline[j]=max(float(np.quantile(vals,.9))-r['elapsed_s'],.001)
            med[j]=max(float(np.median(vals))-r['elapsed_s'],.001)
        fit_info.append(dict(fold=k,train_workflows=len({r['workflow_id'] for j,r in enumerate(rows) if train[j]}),
                             test_workflows=len({r['workflow_id'] for j,r in enumerate(rows) if test[j]})))
        print('fit fold',k,'train',int(train.sum()),'test',int(test.sum()),flush=True)
    for i,r in enumerate(rows):
        r.update(predicted_remaining_s=float(pred[i]),role_p90_remaining_s=float(baseline[i]),role_median_remaining_s=float(med[i]))
    write_csv(OUT/'agent-predictions.csv',rows)
    agent_rows=[]
    for ai,a in enumerate(agents):
        ids=[i for i,r in enumerate(rows) if r['agent_index']==ai]
        errors={}
        for label,est in [('progress',pred),('role_p90',baseline),('role_median',med)]:
            errors[label+'_nmae']=float(np.mean(np.abs(est[ids]-y[ids]))/a['duration_s'])
            errors[label+'_entry_ape']=float(abs(est[ids[0]]-y[ids[0]])/a['duration_s'])
            errors[label+'_mae_s']=float(np.mean(np.abs(est[ids]-y[ids])))
        agent_rows.append(dict(workflow_id=a['workflow_id'],agent_id=a['agent_id'],role=a['role'],
                               duration_s=a['duration_s'],snapshots=len(ids),**errors))
    write_csv(OUT/'agent-errors.csv',agent_rows)
    stats={key:dict(median=float(np.median([r[key] for r in agent_rows])),p90=float(np.quantile([r[key] for r in agent_rows],.9)))
           for key in errors}
    summary=dict(evidence='Offline prediction of observed agent wall-clock durations; workflow-disjoint 5-fold evaluation.',
                 agents=len(agents),workflows=len({a['workflow_id'] for a in agents}),snapshots=len(rows),
                 statistics_unit='One per-agent mean absolute remaining-time error divided by reported total agent duration; requests are repeated snapshots, not independent agents.',
                 feature_numeric=['log_elapsed','log_current_prompt','log_initial_prompt','log_completed_count','log_admitted_count',
                                  'log_completed_api_time','log_completed_output_tokens','log_visible_prompt_sum','log_visible_prompt_max',
                                  'log_last_completed_api_time','log_time_since_completion'],
                 feature_categories=dict(roles=roles,models=models),fold_salt=SALT,folds=fit_info,
                 model_config=config.__dict__,model_source_sha256=sha(model_path),metrics=stats,
                 limitations=['Observed CC timing includes tools and service effects; this is not AegisKV hardware calibration.',
                              'Diagnostic progress GBDT differs from the current role-P90 default; report both and do not attribute its accuracy to P90.',
                              'No repeated physical trials; inference is scoped to this public trace corpus.'])
    (OUT/'agent-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--trace',type=Path,default=TRACE);p.add_argument('--extract',action='store_true');a=p.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    if a.extract or not (OUT/'agent-episodes.jsonl').exists():extract(a.trace)
    analyze()
