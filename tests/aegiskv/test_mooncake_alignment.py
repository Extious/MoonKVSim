from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import hashlib
import pytest
from types import SimpleNamespace

from moonkvsim.aegiskv.experiment import (
    DEFAULT_PARAMETERS, CellSpec, FailureEventSchedule, FailureSchedule, Scenario,
    core_variants, ablation_variants, run_study_cell, _chunks_for_record,
    _StudyRuntime, _ExecutionStatus,
)
from moonkvsim.aegiskv.experiment_workload import load_experiment_records
from moonkvsim.aegiskv.formal_algorithm_audit import (
    audit_continuous_scheduler_evidence, audit_formal_algorithm_run,
)
from moonkvsim.common.hash import sha256_json

def record():
    path = Path(__file__).parents[2] / 'benchmark/AegisKV/experiments/workloads/weka-e2-two-workflow-shapes.jsonl'
    item = dict(load_experiment_records(path)[0])
    tokens = list(range(int(item['prompt_tokens'])))
    digest = sha256_json(tokens)
    item.update(messages_or_token_ids={'kind':'token_ids','sha256':digest,'value':tokens},
                prompt_token_ids_hash=digest, token_count_mode='qwen3_token_ids',
                tokenizer_fingerprint=digest)
    return item

def variant(chunk=4096):
    return core_variants(replace(DEFAULT_PARAMETERS,
        runtime_semantics='mooncake_prompt_v1', policy_chunk_tokens=chunk,
        failure_progress_per_mille=990,gpu_recovery_time_ns=100_000_000))[-1]

def test_runtime_quota_and_candidate_scope_match_native_contract():
    v = variant()
    assert v.profile.peer_replication_fraction == v.profile.store_fraction == 1
    assert not v.profile.cache_aware_routing
    assert v.parameters.peer_hbm_quota_bytes_per_gpu == int(
        Decimal('.2') * v.parameters.physical_hbm_bytes_per_gpu)
    assert v.parameters.kv_capacity_bytes_per_gpu < v.parameters.aimd_capacity_bytes_per_gpu

def test_identical_content_in_distinct_requests_has_distinct_physical_keys():
    first = record()
    second = {**first, 'span_id': str(first['span_id']) + ':independent'}
    p = variant().parameters
    assert {c.key for c in _chunks_for_record(first,p)}.isdisjoint(
        c.key for c in _chunks_for_record(second,p))
    assert _chunks_for_record(first,p) == _chunks_for_record(dict(first),p)

def test_both_bypassed_ordinal_requires_fresh_decisions_on_retry():
    runtime = object.__new__(_StudyRuntime)
    v = variant()
    runtime.parameters, runtime.profile = v.parameters, v.profile
    runtime.executions = {'r':SimpleNamespace(route_version=0,status=_ExecutionStatus.RUNNING)}
    runtime._runtime_gate_frontier = {}; runtime._runtime_gate_outcomes = {}
    runtime._formal_blocked_request_paths = set();runtime._formal_active_request_paths = set()
    runtime.des = SimpleNamespace(now_ns=0);runtime.formal_policy_events=[]
    runtime._formal_finish_request_path=lambda *args,**kwargs: None
    h=(0,'PEER_HBM',0,'h');d=(0,'STORE_DRAM',0,'d')
    runtime._runtime_gate_resolve('r',h,committed=False)
    runtime._runtime_gate_resolve('r',d,committed=False)
    # A retry must not combine a new HBM result with the previous DRAM bypass.
    runtime._runtime_gate_resolve('r',h,committed=True)
    assert runtime._runtime_gate_frontier.get(('r',0),0)==0
    runtime._runtime_gate_resolve('r',d,committed=True)
    assert runtime._runtime_gate_frontier[('r',0)]==1

@pytest.mark.parametrize('arm', ['no_slack', 'no_aimd', 'lru_eviction'])
def test_ablation_retains_request_scope_copy_and_completion_contract(arm):
    v = next(v for v in ablation_variants(variant(256).parameters) if v.variant_id==arm)
    r = run_study_cell([record()],CellSpec(v,'8k',Scenario.NO_FAILURE,0,'A',
                                         workflow_concurrency=1))
    rep = r.representative
    assert rep['transfers']
    assert all(points[-1]['occupied_bytes']==0
               for points in rep['peer_hbm_timelines'].values())
    assert rep['store_dram_timeline'][-1]['occupied_bytes']==0
    audit_continuous_scheduler_evidence(r.payload,rep)

def test_chunk_buffers_wait_for_forward_completion_and_request_cleanup():
    v = variant(256)
    r = run_study_cell([record()],CellSpec(v,'8k',Scenario.NO_FAILURE,0,'A',
                                         workflow_concurrency=1))
    rep = r.representative
    first = rep['continuous_batch_scheduler']['steps'][0]
    puts = [t for t in rep['transfers'] if t['cause'].endswith('_PROTECTION')]
    assert puts
    assert min(t['start_ns'] for t in puts) >= first['effective_end_ns']
    assert any(e['event']=='FORMAL_COMPLETE_REQUEST' for e in rep['formal_algorithm2_events'])
    assert all(points[-1]['occupied_bytes']==0
               for points in rep['peer_hbm_timelines'].values())
    assert rep['store_dram_timeline'][-1]['occupied_bytes']==0
    audit_formal_algorithm_run(r.payload,rep)

def test_route_bound_local_hbm_recovery_copies_then_releases_both_tiers():
    item = record(); v = variant()
    f0 = run_study_cell([item],CellSpec(v,'8k',Scenario.NO_FAILURE,0,'A',
                                      workflow_concurrency=1))
    before = f0.span_details[0]
    schedule = FailureSchedule((FailureEventSchedule(
        failure_id='native-contract',event_index=0,bucket='8k',seed=0,
        focus_span_id=str(item['span_id']),target_gpu_id=str(before['gpu_id']),
        reference_at_ns=int(before['completed_ns'])*990//1000,
        target_workload_progress_per_mille=500,reference_completed_workflow_count=0,
        reference_workflow_count=1,detection_delay_ns=0,trigger_progress_per_mille=990,
        gpu_recovery_time_ns=100_000_000,selection_scope='behavioral-conformance'),),
        selection_scope='behavioral-conformance')
    r = run_study_cell([item],CellSpec(v,'8k',Scenario.GPU_FAILURE,0,'A',
                         failure_schedule=schedule,workflow_concurrency=1))
    rep = r.representative
    detail = r.span_details[0]
    assert detail['restored_peer_tokens'] > 0
    assert detail['restored_peer_local_tokens'] == 0  # no free reclassification
    copies = [t for t in rep['transfers'] if t['path']=='HBM_LOCAL_COPY']
    assert len(copies)==1 and copies[0]['bytes']>0
    assert copies[0]['end_ns'] > copies[0]['start_ns']
    plan = next(e for e in rep['recovery_events'] if e['event']=='RECOVERY_PLAN')
    assert plan['peer_source_gpu_id']==plan['target_gpu_id']
    assert plan['local_peer_activation_bytes']==0
    assert plan['new_recovery_reserve_bytes']>=copies[0]['bytes']
    assert detail['external_output_emissions']==item['output_tokens']
    assert all(points[-1]['occupied_bytes']==0
               for points in rep['peer_hbm_timelines'].values())
    audit_formal_algorithm_run(r.payload,rep)
    audit_continuous_scheduler_evidence(r.payload,rep)


def test_bound_recovery_waits_when_live_primary_kv_occupies_its_target():
    # Two exact-token functional fixtures deliberately collide with one
    # standby. They are not substituted for the paper's frozen workload.
    gpus = tuple(f'gpu-{i}' for i in range(8))
    def route(request, role, candidates=gpus):
        return min(candidates, key=lambda g: -int.from_bytes(hashlib.sha256(
            '\0'.join(('rendezvous-sha256-v1','0',role,request,g)).encode()).digest(),'big'))
    first_id = 'capacity-a'; source = route(first_id,'source:route=1')
    standby = route(first_id,f'failover:route=1:source={source}',tuple(g for g in gpus if g!=source))
    second_id = next(f'capacity-b-{i}' for i in range(100) if route(f'capacity-b-{i}','source:route=1')==standby)
    def long_record(span, duration, output=20):
        item = record(); n = 86016; tokens=list(range(n)); hashes=list(range(n//64))
        digest=sha256_json(tokens)
        item.update(span_id=span,workflow_id=span,session_id=span,prompt_tokens=n,
            output_tokens=output,total_model_tokens=n+output,recorded_api_time_ns=duration,observed_finish_ns=duration,
            source_hash_ids=hashes,source_hash_ids_sha256=sha256_json(hashes),
            messages_or_token_ids={'kind':'token_ids','sha256':digest,'value':tokens},prompt_token_ids_hash=digest)
        return item
    records=[long_record(first_id,79_000_000_000),long_record(second_id,80_000_000_000,400)]
    v=variant(); schedule=FailureSchedule((FailureEventSchedule(
        failure_id='capacity-contract',event_index=0,bucket='96k',seed=0,
        focus_span_id=first_id,target_gpu_id=source,reference_at_ns=78_210_000_000,
        target_workload_progress_per_mille=500,reference_completed_workflow_count=0,
        reference_workflow_count=2,detection_delay_ns=0,trigger_progress_per_mille=990,
        gpu_recovery_time_ns=100_000_000,selection_scope='behavioral-conformance'),),
        selection_scope='behavioral-conformance')
    result=run_study_cell(records,CellSpec(v,'96k',Scenario.GPU_FAILURE,0,'A',
                          failure_schedule=schedule,workflow_concurrency=2))
    waits=[e for e in result.representative['recovery_events'] if e['event']=='BOUND_RECOVERY_CAPACITY_WAIT']
    assert waits and {e['target_gpu_id'] for e in waits}=={standby}
    assert next(d for d in result.span_details if d['span_id']==first_id)['gpu_id']==standby
    audit_formal_algorithm_run(result.payload,result.representative)
    audit_continuous_scheduler_evidence(result.payload,result.representative)
