"""Offline, workflow-disjoint GBDT evaluation of WHOLE-Agent remaining seconds.

No future request metadata are inputs. All request-arrival landmarks are used
for training; the primary figure counts one eligible Agent at request 2 once.
Outputs stay outside paper/ until the evidence has been reviewed.
"""
from pathlib import Path
from collections import Counter, defaultdict
import argparse
import copy
import csv
import hashlib
import json
import platform
import time

import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.feature_extraction import DictVectorizer
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / 'benchmark/AegisKV'
SOURCE = BASE / 'experiments/data/design-insights/agent-episodes.jsonl'
OUT = BASE / 'experiments/data/agent-gbdt-steps'
SALT = 'aegiskv-design-insight-agent-20260918'
LANDMARKS = (1, 2, 5, 10, 20)
CONFIG = dict(loss='absolute_error', learning_rate=.05, max_iter=200,
              max_leaf_nodes=15, min_samples_leaf=40, l2_regularization=1.,
              early_stopping=False, random_state=20260920)
METHODS = ('median', 'gbdt_basic', 'gbdt_history')


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def write_csv(path, rows):
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


def features(start, visible, full=True):
    """Only the visible prefix is accepted; current output/latency are ignored.

    Sequential landmarks are filtered before this function: every prior API
    call has completed, so its output and latency are available.
    """
    now = visible[-1]['t']; current = visible[-1]; past = visible[:-1]
    f = dict(model=current['model'], step=len(visible), elapsed_s=now-start,
             current_prompt_proxy=current['prompt'])
    if not full:
        return f
    f['first_prompt_proxy'] = visible[0]['prompt']
    f['context_growth'] = current['prompt'] - visible[0]['prompt']
    f['elapsed_per_completed_request'] = (now-start)/max(1, len(past))
    f['model_changes'] = sum(a['model'] != b['model'] for a, b in zip(visible, visible[1:]))
    arrivals = np.array([r['t'] for r in visible])
    intervals = np.diff(arrivals)
    gaps = np.array([max(0., b['t']-a['t']-a['latency']) for a,b in zip(visible, visible[1:])])
    growth = np.diff([r['prompt'] for r in visible])
    values = dict(api_s=np.array([r['latency'] for r in past]),
                  output_tokens=np.array([r['output'] for r in past]),
                  interval_s=intervals, gap_s=gaps, prompt_growth=growth)
    for name, array in values.items():
        f[name+'_sum'] = float(array.sum())
        f[name+'_mean'] = float(array.mean()) if len(array) else 0.
        f[name+'_last3_mean'] = float(array[-3:].mean()) if len(array) else 0.
        f[name+'_std'] = float(array.std()) if len(array) else 0.
        for lag in (1, 2, 3):
            f[name+f'_lag{lag}'] = float(array[-lag]) if len(array) >= lag else 0.
    return f


def snapshot_data(agents):
    rows = []; basic = []; history = []; excluded = Counter()
    for ai, a in enumerate(agents):
        rs = a['requests']; start = a['start']; selected = []
        fold = int.from_bytes(hashlib.sha256((SALT+':'+a['workflow_id']).encode()).digest()[:8], 'big') % 5
        for j, r in enumerate(rs):
            # Eligibility depends on whether prior calls have completed by now,
            # never on remaining duration or prediction error.
            if any(p['t']+p['latency'] > r['t'] for p in rs[:j]):
                excluded['overlap_landmarks'] += 1; continue
            if a['duration_s']-(r['t']-start) <= 0:
                raise ValueError('Invalid remaining-time label')
            selected.append(len(rows))
            rows.append(dict(agent_index=ai, workflow_id=a['workflow_id'], agent_id=a['agent_id'],
                             step=j+1, fold=fold, model=r['model'], elapsed_s=r['t']-start,
                             actual_remaining_s=a['duration_s']-(r['t']-start),
                             total_duration_s=a['duration_s']))
            basic.append(features(start, rs[:j+1], False))
            history.append(features(start, rs[:j+1], True))
        for k in selected:
            rows[k]['agent_weight'] = 1./len(selected)
    # A causal-prefix invariance check, material to this evaluation.
    checked = 0
    for a in agents[:100]:
        if len(a['requests']) < 2:
            continue
        rs = a['requests']; before = features(a['start'], rs[:2])
        changed = copy.deepcopy(rs)
        changed[1]['latency'] = 9e9; changed[1]['output'] = 999999999
        for r in changed[2:]:
            for key in ('t', 'prompt', 'output', 'latency'):
                r[key] = 9e9
        assert before == features(a['start'], changed[:2])
        checked += 1
    return rows, basic, history, dict(excluded), checked


def median_baseline(train, test):
    """Same observed request index and model; >=20 Agents or step/global fallback."""
    grouped = defaultdict(list); by_step = defaultdict(list)
    for r in train:
        grouped[(r['step'], r['model'])].append(r['actual_remaining_s'])
        by_step[r['step']].append(r['actual_remaining_s'])
    global_median = float(np.median([r['actual_remaining_s'] for r in train if r['step'] == 1]))
    result = []
    for r in test:
        pool = grouped[(r['step'], r['model'])]
        if len(pool) < 20:
            pool = by_step[r['step']]
        result.append(float(np.median(pool)) if len(pool) >= 20 else global_median)
    return result


def metrics(rows, method):
    y = np.array([r['actual_remaining_s'] for r in rows])
    p = np.array([r[method+'_s'] for r in rows])
    ae = np.abs(y-p); ape = 100*ae/y
    return dict(n_agents=len(rows), n_workflows=len({r['workflow_id'] for r in rows}),
                mae_s=float(ae.mean()), median_ae_s=float(np.median(ae)),
                median_ape_pct=float(np.median(ape)), p90_ape_pct=float(np.percentile(ape,90)),
                within20_pct=float(100*np.mean(ape<=20)), within50_pct=float(100*np.mean(ape<=50)),
                wape_pct=float(100*ae.sum()/y.sum()),
                pearson=float(np.corrcoef(y,p)[0,1]),
                r2=float(1-np.square(y-p).sum()/np.square(y-y.mean()).sum()),
                overprediction_pct=float(100*np.mean(p>y)))


def cluster_bootstrap(rows, repeats=2000):
    """Paired resampling of WORKFLOWS, with every eligible Agent retained."""
    groups = defaultdict(list)
    for r in rows:
        groups[r['workflow_id']].append(r)
    matrix = []
    for rs in groups.values():
        errors = {m:sum(abs(r[m+'_s']-r['actual_remaining_s']) for r in rs) for m in METHODS}
        matrix.append([len(rs), errors['median'], errors['gbdt_basic'], errors['gbdt_history']])
    matrix = np.array(matrix); rng = np.random.default_rng(20260920)
    reduction = []; difference = []
    for _ in range(repeats):
        v = matrix[rng.integers(0,len(matrix),len(matrix))].sum(axis=0)
        reduction.append(100*(1-v[3]/v[1])); difference.append((v[3]-v[1])/v[0])
    return dict(unit='workflow cluster; paired held-out errors, fitted models fixed', repeats=repeats,
                mae_reduction_pct_ci95=np.percentile(reduction,[2.5,97.5]).tolist(),
                mae_difference_s_ci95=np.percentile(difference,[2.5,97.5]).tolist(),
                limitation='Descriptive conditional interval; not retraining uncertainty or temporal deployment validation')


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    agents = [json.loads(s) for s in SOURCE.read_text().splitlines()]
    rows, basic, history, excluded, causal_checks = snapshot_data(agents)
    protocol = dict(created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                    target='Seconds until the reported completion of the whole Agent instance/task, across all future requests and intervening delays',
                    observation='Arrival of each LLM request, only when all prior calls in that Agent have completed; not an explicitly logged tool completion',
                    primary_landmark=2, secondary_landmarks=list(LANDMARKS),
                    primary_metric='Seconds MAE at request 2; remaining-time APE ECDF and tails also mandatory',
                    source=str(SOURCE), source_sha256=sha(SOURCE),
                    source_provenance=json.loads((SOURCE.parent/'agent-extraction.json').read_text()),
                    samples=len(rows), input_agents=len(agents), workflows=len({r['workflow_id'] for r in rows}),
                    exclusions=excluded, causal_invariance_checks=causal_checks,
                    basic_features=sorted(basic[0]), history_features=sorted(history[0]),
                    split='Five folds by whole Workflow ID; identical fold salt to previous early diagnostic',
                    fold_salt=SALT, config=CONFIG, label_transform='None: remaining seconds directly',
                    training_weight='Within each Agent, retained landmarks sum to one; normalized to average training weight one',
                    evaluation_weight='One sample per eligible Agent at each specified landmark; no snapshot pooling in primary figure',
                    tuning='Fixed settings before fitting; no held-out tuning or favorable-landmark selection',
                    baselines='Training-fold median at same request index and model (>=20 samples); else same-index median (>=20), else entry-time global median; basic GBDT ablation',
                    limitations=['Roles are all Subagent; task text, tool identities/results, semantic progress and explicit tool completion times absent',
                                 'Input length is a 64-token hash-block proxy, not exact tokenizer length',
                                 'Completed recorded episodes only; sessions filtered by original corpus',
                                 'Workflow-disjoint cross-validation, not unseen-role or chronological deployment evaluation',
                                 'Raw repeated tasks/users may span workflow IDs; identities not available to audit them',
                                 'Observed service/queue/tool delays included in labels; no physical AegisKV or WCT experiment'],
                    versions=dict(python=platform.python_version(),numpy=np.__version__,sklearn=sklearn.__version__),
                    script_sha256=sha(__file__))
    # Write the evaluation choices before looking at held-out predictions.
    write_json(OUT/'protocol.json', protocol)
    fold_rows=[]; y=np.array([r['actual_remaining_s'] for r in rows]); w=np.array([r['agent_weight'] for r in rows])
    for fold in range(5):
        tr=np.array([i for i,r in enumerate(rows) if r['fold']!=fold])
        te=np.array([i for i,r in enumerate(rows) if r['fold']==fold])
        train=[rows[i] for i in tr]; test=[rows[i] for i in te]
        train_ids={r['workflow_id'] for r in train}; test_ids={r['workflow_id'] for r in test}
        assert not train_ids & test_ids
        for i,p in zip(te,median_baseline(train,test)):
            rows[i]['median_s']=p
        for method, fs in [('gbdt_basic',basic),('gbdt_history',history)]:
            vectorizer=DictVectorizer(sparse=False)
            tx=vectorizer.fit_transform([fs[i] for i in tr]); vx=vectorizer.transform([fs[i] for i in te])
            model=HistGradientBoostingRegressor(**CONFIG)
            start=time.perf_counter()
            with threadpool_limits(limits=4):
                model.fit(tx,y[tr],sample_weight=w[tr]/w[tr].mean())
                fit_s=time.perf_counter()-start; start=time.perf_counter()
                pred=np.maximum(1e-6,model.predict(vx)); predict_s=time.perf_counter()-start
            for i,p in zip(te,pred):
                rows[i][method+'_s']=float(p)
            fold_rows.append(dict(fold=fold,method=method,train_workflows=len(train_ids),test_workflows=len(test_ids),
                                  train_samples=len(tr),test_samples=len(te),fit_s=fit_s,predict_batch_s=predict_s))
            print(json.dumps(fold_rows[-1]),flush=True)
    for r in rows:
        for method in METHODS:
            r[method+'_ape_pct']=100*abs(r[method+'_s']-r['actual_remaining_s'])/r['actual_remaining_s']
    write_csv(OUT/'predictions.csv',rows); write_csv(OUT/'fold-timing.csv',fold_rows)
    summary={}
    for step in LANDMARKS:
        cohort=[r for r in rows if r['step']==step]
        summary[str(step)]={m:metrics(cohort,m) for m in METHODS}
        summary[str(step)]['coverage_of_1688_agents_pct']=100*len(cohort)/len(agents)
        summary[str(step)]['paired_workflow_bootstrap']=cluster_bootstrap(cohort)
    write_json(OUT/'summary.json',summary)
    write_csv(OUT/'primary-landmark.csv',[r for r in rows if r['step']==2])
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':
    run()
