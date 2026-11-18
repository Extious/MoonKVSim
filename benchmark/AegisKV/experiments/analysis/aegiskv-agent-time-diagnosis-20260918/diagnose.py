from pathlib import Path
from collections import defaultdict, Counter
import csv, json, hashlib
import numpy as np

ROOT=Path.cwd(); D=ROOT/'benchmark/AegisKV/experiments/data/design-insights'; OUT=Path(__file__).parent

def read(name):
 rows=list(csv.DictReader((D/name).open()))
 for r in rows:
  for k in r:
   if k not in ['workflow_id','agent_id','role','model']:r[k]=float(r[k])
 return rows

def quant(x):return {str(q):float(np.quantile(x,q)) for q in [0,.1,.25,.5,.75,.9,.95,1]}
def med(x):return float(np.median(list(x)))
def bucket(t):return '<30s' if t<30 else '30-120s' if t<120 else '120-600s' if t<600 else '>=600s'
a=read('agent-errors.csv');p=read('agent-predictions.csv');episodes=[json.loads(s) for s in (D/'agent-episodes.jsonl').open()]
report={'duration_quantiles_s':quant([x['duration_s'] for x in a]),'requests_per_agent_quantiles':quant([x['snapshots'] for x in a])}
report['duration_groups']=[]
for name in ['<30s','30-120s','120-600s','>=600s']:
 aa=[x for x in a if bucket(x['duration_s'])==name];pp=[x for x in p if bucket(x['total_duration_s'])==name];first=[x for x in pp if x['request_index']==0]
 report['duration_groups'].append(dict(group=name,agents=len(aa),snapshot_share=sum(x['snapshots'] for x in aa)/len(p),duration_median_s=med(x['duration_s'] for x in aa),gbdt_nmae_median=med(x['progress_nmae'] for x in aa),median_prior_nmae_median=med(x['role_median_nmae'] for x in aa),p90_prior_nmae_median=med(x['role_p90_nmae'] for x in aa),gbdt_mae_median_s=med(x['progress_mae_s'] for x in aa),snapshot_overprediction_rate=med([0]) if not pp else sum(x['predicted_remaining_s']>x['remaining_s'] for x in pp)/len(pp),entry_prediction_median_s=med(x['predicted_remaining_s'] for x in first),entry_median_prior_s=med(x['role_median_remaining_s'] for x in first),entry_p90_prior_s=med(x['role_p90_remaining_s'] for x in first)))
ntop=int(np.ceil(.1*len(a)))
report['training_weight']={'longest_10pct_agents_snapshot_share':sum(x['snapshots'] for x in sorted(a,key=lambda x:x['duration_s'])[-ntop:])/len(p),'most_requests_10pct_agents_snapshot_share':sum(x['snapshots'] for x in sorted(a,key=lambda x:x['snapshots'])[-ntop:])/len(p)}
report['error_tail']={'gbdt_nmae_gt_1_agents':sum(x['progress_nmae']>1 for x in a),'of_those_duration_lt_60s':sum(x['progress_nmae']>1 and x['duration_s']<60 for x in a)}
report['model_groups']=[]
for model in sorted({x['model'] for x in p}):
 first=[x for x in p if x['request_index']==0 and x['model']==model]
 report['model_groups'].append(dict(model=model,agents=len(first),duration_median_s=med(x['total_duration_s'] for x in first),gbdt_entry_nmae_median=med(abs(x['predicted_remaining_s']-x['remaining_s'])/x['total_duration_s'] for x in first)))
stages=defaultdict(lambda:defaultdict(list))
for x in p:
 progress=x['elapsed_s']/x['total_duration_s'];stage=min(int(progress*4),3)
 stages[stage][int(x['agent_index'])].append(abs(x['predicted_remaining_s']-x['remaining_s'])/x['total_duration_s'])
report['progress_strata_posthoc']=[dict(progress_bin=f'{s*25}-{(s+1)*25}%',agents=len(v),median_agent_mean_nmae=med(np.mean(e) for e in v.values())) for s,v in sorted(stages.items())]
coverage=[];groups=defaultdict(list)
for e in episodes:
 intervals=sorted((x['t'],x['t']+x['latency']) for x in e['requests']);end=-float('inf');covered=0
 for l,r in intervals:covered+=max(0,r-max(l,end));end=max(end,r)
 coverage.append((e['duration_s']-covered)/e['duration_s'])
 q=e['requests'][0];groups[(q['model'],q['prompt'],q['t']-e['start'])].append(e)
report['walltime_outside_api_interval_union_fraction']=quant(coverage)
report['identical_entry_features_groups']=[]
for (model,prompt,elapsed),es in sorted(groups.items(),key=lambda kv:len(kv[1]),reverse=True):
 wfs={e['workflow_id'] for e in es}
 if len(es)<5 or len(wfs)<3:continue
 vals=[e['duration_s'] for e in es]
 report['identical_entry_features_groups'].append(dict(model=model,prompt=prompt,elapsed=elapsed,agents=len(es),workflows=len(wfs),duration_s=quant(vals)))
 if len(report['identical_entry_features_groups'])>=5:break
report['input_sha256']={n:hashlib.sha256((D/n).read_bytes()).hexdigest() for n in ['agent-errors.csv','agent-predictions.csv','agent-episodes.jsonl']}
report['scope']='Post-hoc diagnostics of frozen workflow-held-out predictions; no figure changes, refitting, or feature changes. Duration/progress strata use outcomes only for diagnosis, not as predictor inputs. Outside API intervals cannot be attributed specifically to tool execution from this trace.'
(OUT/'diagnosis.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
