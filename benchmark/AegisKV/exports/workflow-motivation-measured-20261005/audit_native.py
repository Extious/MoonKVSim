"""Independent set-based 20% check from native kernel selection artifacts."""
from pathlib import Path
import json,hashlib,numpy as np
ROOT=Path(__file__).resolve().parent;AEGIS=ROOT.parents[1]
NATIVE=AEGIS/'experiments/workflow-motivation-20261005/runs/native-models-163137'
expected=json.loads((ROOT/'ORIGINAL_TYPE_MEASUREMENTS.json').read_text())['native_concentration']
result=[]
for name in ['NOSA-8B','NSA-8B','MiniCPM4.1-8B']:
 summary=json.loads((NATIVE/name/'SUMMARY.json').read_text());rates=[]
 for request in summary['requests']:
  assert request['observer_max_abs_logit_difference']==0
  assert len(request['layers'])==32
  B=request['history_tokens']//64;layer_rates=[]
  for layer in request['layers']:
   p=NATIVE/name/layer['trace_file'];assert hashlib.sha256(p.read_bytes()).hexdigest()==layer['trace_sha256']
   arr=np.load(p)['selected_blocks'][:,request['history_tokens']:]
   assert arr.shape[1]==512
   counts=np.zeros(B,dtype=np.int64)
   for q in range(512):
    for block in set(int(b) for b in arr[:,q].ravel() if 0<=b<B):counts[block]+=1
   layer_rates.append(sum(sorted(counts,reverse=True)[:B//5])/sum(counts))
  rates.append(100*float(np.mean(layer_rates)))
 value=next(e for e in expected if e['model']==name)
 assert abs(np.mean(rates)-value['top20_mean_percent'])<1e-10
 assert abs(min(rates)-value['top20_min_percent'])<1e-10
 assert abs(max(rates)-value['top20_max_percent'])<1e-10
 result.append({'model':name,'three_history_top20_percent':rates,'mean_percent':float(np.mean(rates)),
    'artifact_hashes_verified':True,'last_query_window':512,'layers':32,'unique_query_block_across_heads':True,
    'instrumentation_changes_logits':False,'production_prevalence_or_recovery_gain_measured':False})
(ROOT/'review/NATIVE_MEASUREMENT_AUDIT.json').write_text(json.dumps(result,indent=2)+'\n')
print('Independent native set counting agrees for all three models; all trace hashes and logit comparisons checked.')
