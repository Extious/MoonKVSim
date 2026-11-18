#!/usr/bin/env python3
"""Frozen, paired prompt-protection study; no measured outcomes are imported."""
from __future__ import annotations
import argparse, json, multiprocessing, time, traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from statistics import mean
from moonkvsim.aegiskv.experiment import (CellSpec, Scenario, SystemId, FailureSchedule,
    core_variants, ablation_variants, derive_failure_schedule, run_study_cell)
from moonkvsim.aegiskv.experiment_config import (repository_root, default_config_dir,
    load_experiment_configs, model_parameters_from_configs, workload_paths)
from moonkvsim.aegiskv.experiment_suite import load_frozen_workload
from moonkvsim.aegiskv.formal_algorithm_audit import (audit_formal_algorithm_run,
    audit_continuous_scheduler_evidence, audit_lru_ablation_run, audit_store_only_control_run)
from moonkvsim.aegiskv.paper_artifacts import file_sha256, write_raw_evidence, load_raw_evidence
from moonkvsim.common.hash import sha256_json
from run_aegiskv_paper_sweeps import _failure_schedule_from_dict

_RECORDS=(); _PARAMETERS=None; _OUTPUT=Path('.'); _CONTRACT={}
ARMS=('unprotected','dram','full','no_slack','no_aimd','lru_eviction')
POINTS={
 'base':dict(concurrency=16,serialization=0,bandwidth=25_000_000_000,failures=1,arms=ARMS),
 'concurrency8':dict(concurrency=8,serialization=0,bandwidth=25_000_000_000,failures=1,arms=('dram','full')),
 'concurrency32':dict(concurrency=32,serialization=0,bandwidth=25_000_000_000,failures=1,arms=('dram','full')),
 'serial500':dict(concurrency=16,serialization=500,bandwidth=25_000_000_000,failures=1,arms=('dram','full')),
 'serial1000':dict(concurrency=16,serialization=1000,bandwidth=25_000_000_000,failures=1,arms=('dram','full')),
 'bandwidth5':dict(concurrency=16,serialization=0,bandwidth=5_000_000_000,failures=1,arms=('dram','full')),
 'failures2':dict(concurrency=16,serialization=0,bandwidth=25_000_000_000,failures=2,arms=('dram','full')),
}

def write(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 temporary=path.with_suffix(path.suffix+'.tmp');temporary.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n');temporary.replace(path)

def params(point):
 x=POINTS[point]
 return replace(_PARAMETERS,batch_serialization_per_mille=x['serialization'],
                peer_bandwidth_bytes_per_second=x['bandwidth'],store_bandwidth_bytes_per_second=x['bandwidth'])

def variant(point,arm):
 p=params(point)
 ids={'unprotected':SystemId.RECOMPUTE_ONLY,'dram':SystemId.AEGIS_DRAM_ONLY,'full':SystemId.AEGIS_UNIFIED}
 if arm in ids:v=next(v for v in core_variants(p) if v.profile.system_id==ids[arm])
 else:v=next(v for v in ablation_variants(p) if v.variant_id==arm)
 return replace(v,suite='mooncake_aligned_paper',variant_id=arm)

def plan_key(point):
 return point if point in ('base','concurrency8','concurrency32','failures2') else 'base'

def plan(point_seed):
 point,seed=point_seed; path=_OUTPUT/'plans'/f'{point}-seed{seed}.json'
 if path.exists():
  doc=json.loads(path.read_text());assert doc['contract']==_CONTRACT['fingerprint'];return str(path)
 reference=repository_root()/'reference/aligned-logical-plans-v1'/path.name
 if reference.exists():
  original=json.loads(reference.read_text())
  schedule=_failure_schedule_from_dict(original['schedule'])
  assert schedule.fingerprint==original['schedule_fingerprint']
  write(path,{**original,'contract':_CONTRACT['fingerprint'],
       'imported_reference':{'sha256':file_sha256(reference),'original_contract':original['contract'],
       'reason':'unprotected reference execution never invokes the corrected protection gate; no measured outcomes imported'}})
  print(f'PLAN IMPORT {point} seed={seed}',flush=True)
  return str(path)
 t=time.monotonic();p=params(point)
 control=variant(point,'unprotected')
 oracle=derive_failure_schedule(_RECORDS,bucket='96k',seed=seed,parameters=p,
      workflow_concurrency=POINTS[point]['concurrency'],workflow_admission_seed=seed,
      peer_binding_seed=0,failure_count=POINTS[point]['failures'],compared_profiles=(control.profile,),
      freeze_post_treatment_impact_contracts=False)
 schedule=FailureSchedule(tuple(replace(e,physical_target_frozen=False,impact_contract=None,
                     profile_impact_contracts=None) for e in oracle.events),
                     selection_scope='unprotected_reference_logical_focus_natural_variant_routing')
 write(path,dict(contract=_CONTRACT['fingerprint'],point=point,seed=seed,
                 schedule=schedule.to_dict(),schedule_fingerprint=schedule.fingerprint,
                 oracle_schedule=oracle.to_dict(),wall_seconds=time.monotonic()-t))
 print(f'PLAN {point} seed={seed} wall={time.monotonic()-t:.1f}',flush=True)
 return str(path)

def audit(raw,job):
 point,seed,scenario,arm=job
 payload=raw['payload'];rep=raw['representative'];details=raw['span_details'];metrics=payload['metrics']
 assert payload['status']=='PASS' and {d['span_id'] for d in details}=={r['span_id'] for r in _RECORDS}
 assert len(details)==len(_RECORDS)
 assert {d['workflow_id'] for d in details}=={r['workflow_id'] for r in _RECORDS}
 assert all(d['completed_ns'] is not None and d['external_output_emissions']==d['output_tokens'] for d in details)
 scheduler=audit_continuous_scheduler_evidence(payload,rep).to_dict()
 if arm=='lru_eviction':policy=audit_lru_ablation_run(payload,rep)
 elif arm=='unprotected':policy=audit_store_only_control_run(payload,rep)
 else:policy=audit_formal_algorithm_run(payload,rep,expected_aimd_enabled=arm not in ('dram','no_aimd'),
             expected_tiers=('STORE_DRAM',) if arm=='dram' else ('PEER_HBM','STORE_DRAM')).to_dict()
 expected=POINTS[point]['failures'] if scenario=='F1' else 0
 assert metrics['failure_impact']['failure_event_count']==expected
 assert metrics['gpu_capacity_recovery']['completed_count']==expected
 assert metrics['resource_cost']['transfer_byte_conservation_valid'] is True
 assert all(points[-1]['occupied_bytes']==0 for points in rep['peer_hbm_timelines'].values())
 assert rep['store_dram_timeline'][-1]['occupied_bytes']==0
 assert all(d['restored_peer_local_tokens']==0 for d in details)
 assert all(d['reused_primary_tokens']==0 and d['reused_store_tokens']==0 for d in details)
 reconstructed={}
 for d in details:
  w=d['workflow_id'];start,end=reconstructed.get(w,(d['released_ns'],d['completed_ns']))
  reconstructed[w]=(min(start,d['released_ns']),max(end,d['completed_ns']))
 wct={w:end-start for w,(start,end) in reconstructed.items()}
 assert wct==metrics['workflow_completion_time_ns']['by_workflow_id']
 # Each local recovery has positive service and a distinct full primary destination.
 for transfer in rep['transfers']:
  if transfer['path']=='HBM_LOCAL_COPY' and transfer['status']=='COMMITTED':
   assert transfer['bytes']>0 and transfer['end_ns']>transfer['start_ns']
 for event in rep['recovery_events']:
  if event['event']=='RECOVERY_PLAN':
   assert event['local_peer_activation_bytes']==0
   assert event['new_recovery_reserve_bytes']>0
 events=rep['formal_algorithm2_events']
 owners={}
 for e in events:
  if 'CONTENT_ALIAS_COMMITTED' in e['event']:
   key=(e['pool_id'],e['physical_chunk_key'])
   assert owners.setdefault(key,e['span_id'])==e['span_id']
   d=next(d for d in details if d['span_id']==e['span_id'])
   assert d['failure_at_ns'] is not None and e['timestamp_ns']>=d['failure_at_ns']
 for d in details:
  if d['failure_at_ns'] is not None and d['recovery_ready_ns'] is not None:
   assert (d['recovery_normal_hbm_local_tokens']+d['restored_peer_tokens']+
           d['restored_store_tokens']+d['recompute_tokens'])==next(r['prompt_tokens'] for r in _RECORDS if r['span_id']==d['span_id'])
 return dict(wct_ns=wct,metrics=metrics,workflow_admission=payload['workflow_admission'],
             failure_events=rep['failure_events'],span_details=details,
             scheduler_audit=scheduler,policy_audit=policy,
             recovery_wait_count=sum(e['event']=='BOUND_RECOVERY_CAPACITY_WAIT' for e in rep['recovery_events']),
             ordinal_count=sum(e['event']=='RUNTIME_SHARED_ORDINAL_ADVANCED' for e in events),
             raw_component_sha256={k:sha256_json(raw[k]) for k in ('payload','representative','span_details')})

def run(job):
 point,seed,scenario,arm=job
 directory=_OUTPUT/'runs'/point/f'seed{seed}';stem=f'{scenario}-{arm}'
 checkpoint=directory/f'{stem}.json';rawpath=directory/f'{stem}.raw.json.gz'
 identity=dict(contract=_CONTRACT['fingerprint'],job=list(job),variant=variant(point,arm).fingerprint)
 t=time.monotonic()
 if checkpoint.exists():
  doc=json.loads(checkpoint.read_text());assert doc['identity']==identity
  assert file_sha256(rawpath)==doc['raw_evidence']['sha256']
  return str(checkpoint)
 plan_doc=json.loads((_OUTPUT/'plans'/f'{plan_key(point)}-seed{seed}.json').read_text())
 schedule=_failure_schedule_from_dict(plan_doc['schedule']) if scenario=='F1' else None
 result=run_study_cell(_RECORDS,CellSpec(variant(point,arm),'96k',Scenario.GPU_FAILURE if schedule else Scenario.NO_FAILURE,
          seed,'A',failure_schedule=schedule,workflow_concurrency=POINTS[point]['concurrency'],
          workflow_admission_seed=seed,peer_binding_seed=0))
 raw=dict(schema='moonkvsim.aligned_paper_raw.v1',identity=identity,payload=result.payload,
          representative=result.representative,span_details=result.span_details,journal_sha256=result.journal_sha256)
 binding=write_raw_evidence(rawpath,raw)
 summary=audit(raw,job)
 write(checkpoint,dict(identity=identity,raw_evidence=binding,summary=summary,wall_seconds=time.monotonic()-t))
 print(f'PASS {point} seed={seed} {stem} wall={time.monotonic()-t:.1f}',flush=True)
 return str(checkpoint)

def verify(job):
 point,seed,scenario,arm=job;directory=_OUTPUT/'runs'/point/f'seed{seed}';stem=f'{scenario}-{arm}'
 doc=json.loads((directory/f'{stem}.json').read_text())
 raw=load_raw_evidence(directory/f'{stem}.raw.json.gz',expected_sha256=doc['raw_evidence']['sha256'])
 assert raw['identity']==doc['identity'] and doc['identity']['contract']==_CONTRACT['fingerprint']
 assert audit(raw,job)==doc['summary']
 return {'job':list(job),'raw_sha256':doc['raw_evidence']['sha256'],'status':'PASS'}

def main():
 global _RECORDS,_PARAMETERS,_OUTPUT,_CONTRACT
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
 parser.add_argument('--jobs',type=int,default=32);parser.add_argument('--phase',choices=('run','verify'),default='run')
 args=parser.parse_args();_OUTPUT=args.output.resolve();root=repository_root()
 snapshot=json.loads((root/'SOURCE_SNAPSHOT.json').read_text())
 # The snapshot records exact working-tree contents, including untracked code.
 for name,digest in snapshot['files'].items():
  assert file_sha256(root/name)==digest, f'source drift: {name}'
 configs=load_experiment_configs(default_config_dir(root),root=root)
 _PARAMETERS=model_parameters_from_configs(configs)
 assert _PARAMETERS.runtime_semantics=='mooncake_prompt_v1'
 paths=workload_paths(configs.requests,root=root)
 _RECORDS,_,_=load_frozen_workload(*paths,retain_exact_token_ids=True)
 assert len(_RECORDS)==1304 and len({r['workflow_id'] for r in _RECORDS})==160
 jobs=[(p,s,f,a) for p,x in POINTS.items() for s in range(5)
       for f in (('F1',) if p=='failures2' else ('F0','F1')) for a in x['arms']]
 contract=dict(schema='moonkvsim.aligned_paper_protocol.v1',source_sha256=sha256_json(snapshot),
  reference_plan_manifest_sha256=(file_sha256(root/'reference/aligned-logical-plans-v1/IMPORT.json')
      if (root/'reference/aligned-logical-plans-v1/IMPORT.json').exists() else None),
  workload_sha256=[file_sha256(p) for p in paths],points=POINTS,seeds=list(range(5)),jobs=jobs,
  expected_measured_runs=len(jobs),failure_focus='96k eligibility; nearest workload progress in unprotected oracle',
  selection_reference='base plans reused for service/bandwidth sensitivity; concurrency and F2 derive separate reference plans',
  estimand='logical focus fault at 60 percent request progress; natural per-policy routing and collateral victims',
  inference='paired Student t intervals across five admission permutations; finite derived workload; no multiplicity adjustment')
 _CONTRACT={**contract,'fingerprint':sha256_json(contract)}
 if (_OUTPUT/'PROTOCOL.json').exists():assert sha256_json(json.loads((_OUTPUT/'PROTOCOL.json').read_text()))==sha256_json(_CONTRACT)
 else:write(_OUTPUT/'PROTOCOL.json',_CONTRACT)
 context=multiprocessing.get_context('fork');started=time.monotonic()
 with ProcessPoolExecutor(max_workers=args.jobs,mp_context=context) as pool:
  if args.phase=='run':
   futures=[pool.submit(plan,(p,s)) for p in ('base','concurrency8','concurrency32','failures2') for s in range(5)]
   for future in as_completed(futures):future.result()
   write(_OUTPUT/'PLANS_READY.json',dict(status='PASS',plan_count=20,contract=_CONTRACT['fingerprint']))
   futures=[pool.submit(run,j) for j in jobs]
   for future in as_completed(futures):future.result()
   write(_OUTPUT/'EXECUTION.json',dict(status='PASS',measured_runs=len(jobs),wall_seconds=time.monotonic()-started,
                                    contract=_CONTRACT['fingerprint']))
  else:
   futures=[pool.submit(verify,j) for j in jobs];accepted=[f.result() for f in as_completed(futures)]
   write(_OUTPUT/'ACCEPTANCE.json',dict(status='PASS',accepted_runs=sorted(accepted,key=lambda x:x['job']),
       measured_runs=len(accepted),contract=_CONTRACT['fingerprint'],wall_seconds=time.monotonic()-started))
if __name__=='__main__':main()
