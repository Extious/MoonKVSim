"""Check new raw execution invariants independently of plotting arrays."""
from pathlib import Path
import hashlib,json,collections,itertools,csv
ROOT=Path(__file__).resolve().parent;AEGIS=ROOT.parents[1]
EXP=AEGIS/'experiments/workflow-motivation-20261005';RUNS=EXP/'runs'
def read(p):return json.loads(p.read_text())
report={}
for job,files in [(163136,['isolated_replay.py','isolated_replay.sbatch']),(163137,['native_models.py','native_models.sbatch'])]:
 hashes=read(EXP/f'source-snapshot-{job}/SHA256.json')
 for name in files:
  assert hashlib.sha256((EXP/name).read_bytes()).hexdigest()==hashes[name]
 report[f'source_snapshot_{job}']='matches submitted/current source'
design=read(AEGIS/'docs/workload-decision-20261004/WORKFLOW_DEPENDENCIES.json')['dependencies']
source=RUNS/'capture-163125';calls=[read(p) for p in (source/'calls').glob('*.json')];healthy=[r for r in calls if r['run_id']=='F0']
assert len(healthy)==36 and len({r['agent_key'] for r in healthy})==15
followups=[r for r in healthy if r['round_index']>0];assert len(followups)==21 and all(r['cached_prefix_tokens']>0 for r in followups)
assert all(r['tool_time_ns']==0 for r in healthy)
assert all(r['kv_tensor_bytes']==r['cache_tokens']*147456 for r in healthy)
for key in {r['agent_key'] for r in healthy}:
 states=sorted((r for r in healthy if r['agent_key']==key),key=lambda r:r['round_index'])
 assert 2<=len(states)<=4
 for a,b in zip(states,states[1:]):assert b['submit_ns']>=a['finish_ns'] and b['cached_prefix_tokens']<=a['cache_tokens']
gpu0=[r for r in healthy if r['worker']==0];gpu1=[r for r in healthy if r['worker']==1]
overlap=sum(max(0,min(a['finish_ns'],b['finish_ns'])-max(a['execution_start_ns'],b['execution_start_ns'])) for a,b in itertools.product(gpu0,gpu1))
assert overlap>0
report['source_capture']={'inputs':2,'healthy_invocations':36,'agents':15,'reused_followups':21,'concurrent_gpu_forward_intervals_seconds':overlap/1e9,'zero_tools':True,'tensor_bytes_per_token':147456}
# The free-generation F1 attempt is explicitly retained as an invalid pair.
invalid=read(source/'pair-token-audit.json');report['free_generation_pair_invalid']=not all(r.get('output_equal',False) for r in invalid)
folder=RUNS/'isolated-163136';summary=read(folder/'SUMMARY.json');assert summary['calls']==450 and summary['input_equal_all'] and summary['output_equal_all']
rows=[read(p) for p in (folder/'calls').glob('*.json')];index={(r['run_id'],r['agent_key'].split('/')[-1],r['round_index']):r for r in rows}
assert len(rows)==450
for w in summary['workflows']:
 assert w['deps']==design['research']
 assert w['wct_ms']==(w['finish_ns']-w['arrival_ns'])/1e6
 for agent,r in w['agents'].items():
  assert all(r['ready_ns']>=w['agents'][p]['finish_ns'] for p in r['parents'])
pairs=[]
for victim in ['A','B','C','G']:
 for trial in range(3):
  run0=f'{victim}_P{trial}_F0';run1=f'{victim}_P{trial}_F1'
  w0=next(w for w in summary['workflows'] if w['run_id']==run0);w1=next(w for w in summary['workflows'] if w['run_id']==run1)
  for agent in design['research']:
   n=w0['agents'][agent]['calls'];assert n==w1['agents'][agent]['calls']
   for local in range(n):
    a=index[run0,agent,local];b=index[run1,agent,local]
    assert a['input_token_ids']==b['input_token_ids'] and a['output_token_ids']==b['output_token_ids']
  before=index[run1,victim,0];next0=index[run0,victim,1];next1=index[run1,victim,1]
  assert before['fault']['victim_agent_keys']==[before['agent_key']]
  assert before['fault']['lost_kv_tensor_bytes']==before['kv_tensor_bytes']
  assert next0['cached_prefix_tokens']>0 and next1['cached_prefix_tokens']==0
  pairs.append(dict(agent=victim,trial=trial,delta_wct_s=(w1['finish_ns']-w1['arrival_ns']-w0['finish_ns']+w0['arrival_ns'])/1e9,
    extra_first_forward_ms=next1['first_forward_cuda_ms']-next0['first_forward_cuda_ms']))
with (ROOT/'data/isolated-agent-kv-loss.csv').open() as f:
 plotted=list(csv.DictReader(f))
for pair,row in zip(pairs,plotted):
 assert pair['agent']==row['agent'] and pair['trial']==int(row['trial'])
 assert abs(pair['delta_wct_s']-float(row['delta_wct_s']))<1e-10
 assert abs(pair['extra_first_forward_ms']/1000-float(row['extra_prefill_s']))<1e-12
report['isolated_pairs']={'workflow_replays':25,'pairs':12,'pairs_per_victim':3,'calls':450,'input_output_equal':True,'single_agent_cache_loss_verified':True,'raw_pairs':pairs,'negative_wct_pairs':sum(p['delta_wct_s']<0 for p in pairs),'wct_is_independent_recorded_wall_time':True}
profiles=read(source/'recovery-profile.json');assert len(profiles)==6
assert all(len(p['measurements'])==3 and all(m['restored_tensor_equal'] for m in p['measurements']) for p in profiles)
report['microprofile']={'natural_prefixes':6,'timing_repetitions_per_prefix':3,'all_restored_tensors_equal':True,'h2d_component_only':True}
(ROOT/'review/MEASUREMENT_AUDIT.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='isolated_pairs'},indent=2));print('Matched isolated pairs:',len(pairs),'negative WCT differences:',report['isolated_pairs']['negative_wct_pairs'])
