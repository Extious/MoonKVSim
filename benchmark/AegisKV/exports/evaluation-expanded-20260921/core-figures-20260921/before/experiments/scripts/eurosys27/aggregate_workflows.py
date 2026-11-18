#!/usr/bin/env python3
"""Paired campaign aggregation of real workflow logs; no fabricated runs.

Complete-case estimates are accompanied by explicit completion/exclusion
counts. This tool does not implement a censoring/RMST estimator.
"""
import argparse
import csv
import hashlib
import json
import os
import shlex
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np


def aggregate(rows, baseline, metric, seed=20260920):
    records={};policies=sorted({r['policy'] for r in rows})
    if not policies:raise ValueError('No raw workflow rows')
    if metric=='difference' and baseline not in policies:raise ValueError('Baseline missing')
    cases=defaultdict(set);completion=defaultdict(lambda:{'completed':0,'total':0})
    for r in rows:
        if r['condition'] not in ['healthy','fault']:raise ValueError('Invalid condition')
        case=(float(r['x']),r['campaign_id'],r['pair_id'],r['workflow_id'])
        key=case+(r['policy'],r['condition'])
        if key in records:raise ValueError(f'Duplicate workflow condition: {key}')
        if r['status']=='completed':
            value=float(r['wct_s'])
            if not np.isfinite(value) or value<0:raise ValueError('Invalid WCT')
        else:value=None
        records[key]=value;cases[case].add((r['policy'],r['condition']))
        ck=(float(r['x']),r['policy'],r['condition'])
        completion[ck]['total']+=1;completion[ck]['completed']+=value is not None
    expected={(p,c) for p in policies for c in ['healthy','fault']}
    for case,observed in cases.items():
        if observed!=expected:
            raise ValueError(f'Incomplete policy/condition mates for {case}; missing {expected-observed}')
    by_campaign=defaultdict(list);excluded=defaultdict(int);eligible=defaultdict(int)
    for case in cases:
        if any(records[case+(p,c)] is None for p,c in expected):
            excluded[case[0]]+=1;continue
        eligible[case[0]]+=1
        penalty={p:records[case+(p,'fault')]-records[case+(p,'healthy')] for p in policies}
        for p in policies:
            value=penalty[p] if metric=='penalty' else penalty[baseline]-penalty[p]
            by_campaign[(case[0],p,case[1])].append(value)
    cells=defaultdict(list)
    for (x,p,campaign),values in sorted(by_campaign.items()):
        cells[(x,p)].append(float(np.mean(values)))
    rng=np.random.default_rng(seed);result=[]
    for (x,p),values in sorted(cells.items()):
        a=np.asarray(values);n=len(a)
        low=high=''
        if n>=2:
            boot=rng.choice(a,size=(10000,n),replace=True).mean(axis=1)
            low,high=np.quantile(boot,[.025,.975]).tolist()
        result.append({'series':p,'x':x,'y':float(a.mean()),'lower':low,'upper':high,'independent_runs':n})
    ledger={'metric':metric,'baseline':baseline,'bootstrap_seed':seed,
      'statistical_unit':'independent paired campaign; mean over shared complete-case cohort within campaign',
      'completion':[dict(x=k[0],policy=k[1],condition=k[2],**v) for k,v in sorted(completion.items())],
      'shared_complete_cases':dict(eligible),'excluded_incomplete_cases':dict(excluded),
      'limitation':'Complete-case estimate only. Report completion and a separately validated restricted-time/censoring analysis.'}
    if not result:raise ValueError('No shared complete cases; report completion instead of a latency estimate')
    return result,ledger


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--raw',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--baseline',default='LRU');p.add_argument('--metric',choices=['penalty','difference'],default='penalty')
    p.add_argument('--figure',default='capacity-frontier');p.add_argument('--panel',default='budget')
    p.add_argument('--bootstrap-seed',type=int,default=20260920)
    a=p.parse_args();rows=list(csv.DictReader(a.raw.open()))
    summaries,ledger=aggregate(rows,a.baseline,a.metric,a.bootstrap_seed)
    a.output.mkdir(parents=True,exist_ok=True)
    command=shlex.join([sys.executable,str(Path(__file__).resolve()),*sys.argv[1:]])
    raw_digest=hashlib.sha256(a.raw.read_bytes()).hexdigest()
    if a.metric=='difference':
        # A policy improvement is not an absolute failure penalty. Keep the
        # companion report out of the plotting CSVs with fixed penalty axes.
        report={'evidence':'measured','quantity':'baseline_penalty_minus_policy_penalty',
                'unit':'s','positive_means':'improvement','baseline':a.baseline,
                'estimates':summaries,'completion_ledger':ledger,
                'raw_source':str(a.raw.resolve()),'raw_sha256':raw_digest,
                'aggregation_command':command}
        path=a.output/'paired-differences.json'
        path.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'paired_difference_report':str(path)},indent=2))
        return
    path=a.output/(a.figure+'.csv');formatted=[]
    for s in summaries:
        formatted.append(dict(figure=a.figure,panel=a.panel,series=s['series'],x=s['x'],y=s['y'],
         lower=s['lower'],upper=s['upper'],unit='s',evidence='measured',scenario_id='shared-complete-cases',
         source_id='workflow-logs',independent_runs=s['independent_runs']))
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(formatted[0]));w.writeheader();w.writerows(formatted)
    (a.output/'completion-ledger.json').write_text(json.dumps(ledger,indent=2)+'\n')
    manifest={'schema_version':1,'evidence':'measured','statistical_unit':ledger['statistical_unit'],
       'aggregation_command':command,
       'uncertainty':'95% percentile paired-campaign bootstrap, 10000 resamples; no interval for n=1',
       'raw_sources':[{'id':'workflow-logs','path':os.path.relpath(a.raw.resolve(),a.output.resolve()),
                      'sha256':raw_digest}],
       'tables':{path.name:hashlib.sha256(path.read_bytes()).hexdigest()}}
    (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'cells':len(summaries),'completion_ledger':str(a.output/'completion-ledger.json')},indent=2))


if __name__=='__main__':main()
