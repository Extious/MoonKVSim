#!/usr/bin/env python3
"""Exact arithmetic for the independent-Agent rental DESIGN, not a runtime."""
from copy import deepcopy
from dataclasses import dataclass, field
from fractions import Fraction as F
from pathlib import Path
import hashlib, json

OUT=Path(__file__).resolve().parent

def benefit(before,after,slack):
    assert before>=after>=0 and slack>=0
    return min(F(before)-F(after),max(F(before)-F(slack),F(0)))

@dataclass
class Block:
    size: int
    credit: dict
    parent: str = None
    pinned: bool = False  # Read or in-progress backup operation protection.
    requests: dict = field(default_factory=dict)
    @property
    def total(self):return sum(self.credit.values(),F(0))

def renew(block,agent,request,value):
    """Actual reuse only. Other Agents' balances are untouched."""
    previous=block.requests.get(agent,-1)
    if request<previous:raise ValueError('stale request')
    if request>previous:
        block.credit[agent]=F(value)
        block.requests[agent]=request

def stage_event(live,key,agent,request,estimate,*,size,current_request,busy=(),ready=True):
    """One actor event through the diagram's wait/duplicate/grant steps.

    Returns a staged ledger; callers publish it only after resident save or a
    successful current-generation copy. No history-wide granting is possible.
    """
    if key in busy:return 'WAIT',None
    block=deepcopy(live[key]) if key in live else Block(size,{})
    seen=block.requests.get(agent,-1)
    if request<current_request or request<seen:return 'STALE',None
    assert request==current_request
    if request==seen:return 'DUPLICATE',None
    # A missing copy cannot bid without a complete source and committed prefix.
    # Existing-copy renewal has no such new-copy prerequisite.
    if key not in live and not ready:return 'WAIT',None
    renew(block,agent,request,estimate(agent))
    return ('RESIDENT' if key in live else 'NEW'),block

def charge(blocks):
    delta=min(b.total/b.size for b in blocks)
    paid=[]
    for b in blocks:
        total=b.total
        debit=b.size*delta
        if total:
            b.credit={a:c*(1-debit/total) for a,c in b.credit.items()}
        assert b.total==total-debit and min(b.credit.values(),default=0)>=0
        paid.append(debit)
    return delta,paid

def plan(live,key,candidate,capacity):
    """Trial prefix-safe replacement, with candidate-first tie rejection."""
    assert key not in live and candidate.size>0
    trial=deepcopy(live);x=deepcopy(candidate);removed=[];trace=[]
    protected=set();parent=x.parent
    while parent:
        assert parent in live
        protected.add(parent);parent=live[parent].parent
    free=capacity-sum(b.size for b in trial.values())
    assert free>=0
    while free<x.size:
        parents={b.parent for b in trial.values()}
        q=sorted(y for y,b in trial.items()
                 if y not in parents and y not in protected and not b.pinned)
        if not q or x.total<=0:
            return False,None,removed,trace
        delta,paid=charge([trial[y] for y in q]+[x])
        trace.append({'q':q,'delta':delta,'paid':paid,'candidate_remaining':x.total})
        if x.total==0:return False,None,removed,trace
        victim=next(y for y in q if trial[y].total==0)
        removed.append(victim);free+=trial.pop(victim).size
    trial[key]=x
    assert sum(b.size for b in trial.values())<=capacity
    assert all(b.parent is None or b.parent in trial for b in trial.values())
    return True,trial,removed,trace

checks={}
# No workflow membership, graph or Agent ordering enters the benefit function.
g={a:benefit(12,8,0) for a in ['A','B']}
assert g=={'A':4,'B':4} and sum(g.values())==8
joint_parallel=max(12,12)-max(8,8)
assert joint_parallel==4
checks['independent_values_add_only_in_credit']={
    'each_Agent':g,'initial_shared_credit':8,
    'illustrative_joint_parallel_WCT_gain':joint_parallel,
    'meaning':'Credit is additive priority, not exact joint WCT gain'}
# The individual formula is exact for fixed Slack and one changing delay.
cases=0
for before in range(15):
    for after in range(before+1):
        for slack in range(17):
            assert benefit(before,after,slack)==max(before-slack,0)-max(after-slack,0)
            cases+=1
checks['single_Agent_Slack_identity']={'exact_cases':cases}
b=Block(1,{'A':F(1),'B':F(1)},requests={'A':1,'B':1})
for r,s,expected in [(2,10,2),(3,13,0),(4,0,4)]:
    renew(b,'A',r,benefit(12,8,s))
    assert b.credit=={'A':expected,'B':1}
checks['actor_only_Slack_renewal']={'Slack':[10,13,0],'A_credit':[2,0,4],'B_credit_unchanged':1}
charge([b]);snapshot=deepcopy(b)
renew(b,'A',4,benefit(12,8,0))
assert b==snapshot
try:renew(b,'A',3,4)
except ValueError:pass
else:raise AssertionError('old request renewed')
fresh=Block(1,{'A':F(4)},requests={'A':9})
charge([fresh]);renew(fresh,'A',9,4)
assert fresh.total==0
checks['duplicate_and_old_request_no_refill']={
    'same_request_after_rent':'unchanged','old_request':'rejected',
    'first_copy_and_hit_same_request':'no second grant'}

shared=Block(4,{'A':F(3),'B':F(5)})
other=Block(3,{'C':F(3)})
delta,paid=charge([shared,other])
assert (delta,paid)==(1,[4,3]) and shared.credit=={'A':F(3,2),'B':F(5,2)}
zero=Block(2,{'D':F(0)});snapshot=deepcopy(shared)
assert charge([shared,zero])==(0,[0,0]) and shared==snapshot
checks['physical_rent_shared_proportions']={
    'delta':delta,'physical_charges':paid,'shared_remaining':shared.credit,
    'zero_credit_division_skipped':True}

live={'old':Block(1,{'A':F(2)})};snapshot=deepcopy(live)
ok,result,victims,trace=plan(live,'new',Block(1,{'B':F(5)}),1)
assert ok and victims==['old'] and result['new'].total==3 and live==snapshot
checks['admitted_candidate_keeps_paid_rent']={'initial':5,'rent':2,'published_credit':3}
for old,new in [(5,2),(2,2)]:
    live={'old':Block(1,{'A':F(old)})};snapshot=deepcopy(live)
    ok,result,_,_=plan(live,'new',Block(1,{'B':F(new)}),1)
    assert not ok and result is None and live==snapshot
ok,result,victims,trace=plan({},'zero',Block(1,{'A':F(0)}),1)
assert ok and not victims and not trace and result['zero'].total==0
checks['loss_tie_and_free_zero_admission']={
    'weaker_candidate':'rejected','tied_candidate':'rejected',
    'zero_credit_with_free_space':'accepted','rejected_trial_live_ledger':'unchanged'}

live={name:Block(1,{name:F(1)}) for name in ['oldB','oldA']}
ok,result,victims,trace=plan(live,'large',Block(2,{'C':F(6)}),2)
assert ok and victims==['oldA','oldB'] and result['large'].total==4
assert [t['delta'] for t in trace]==[1,0]
checks['multiple_victims_and_zero_rent_step']={
    'victims':victims,'deltas':[t['delta'] for t in trace],'candidate_remaining':4}

live={'root':Block(1,{'A':F(10)}),'tail':Block(1,{'A':F(1)},parent='root')}
snapshot=deepcopy(live)
ok,result,victims,trace=plan(live,'large',Block(2,{'B':F(8)}),2)
assert not ok and victims==['tail'] and trace[-1]['candidate_remaining']==0
assert live==snapshot and 'tail' in live
checks['rejection_after_tentative_deletion_rolls_back']={
    'tentative_victim':victims,'live_prefix_and_balances':'unchanged'}

root=Block(1,{'A':F(1,2)},pinned=True,requests={'A':1})
renew(root,'A',2,benefit(7,6,0))
assert root.total==1
live={'root':root,'tail':Block(1,{'A':F(5)},parent='root')}
ok,result,victims,trace=plan(live,'new',Block(1,{'B':F(8)}),2)
assert ok and victims==['tail'] and result['root']==root and result['new'].total==3
checks['internal_pinned_renewal_excluded_from_rent']={
    'root_renewed':1,'root_credit_after_tail_rent':1,'only_victim':'tail'}
# All available space is protected: neither missing prefix nor read pin is bypassed.
live={'prefix':Block(1,{'A':F(0)})}
assert not plan(live,'next',Block(1,{'A':F(9)},parent='prefix'),1)[0]
live={'read':Block(1,{'A':F(0)},pinned=True)}
assert not plan(live,'new',Block(1,{'A':F(9)}),1)[0]
live={'other_copy_prefix':Block(1,{'A':F(0)},pinned=True)}
assert not plan(live,'new',Block(1,{'A':F(9)}),1)[0]
checks['empty_eligible_queue']={'candidate_prefix':'protected','read_pin':'protected','other_copy_operation_pin':'protected'}
# Rejecting forever does not consume real rent; no unconditional idle expiry claim.
live={'old':Block(1,{'A':F(5)})};snapshot=deepcopy(live)
for _ in range(10):assert not plan(live,'new',Block(1,{'B':F(2)}),1)[0]
assert live==snapshot
checks['no_unconditional_idle_expiry']={'rejected_trials':10,'old_credit':5}

# One new-copy event gives only its actor credit. Historical shared references
# belong to metadata, not a new batch of unrequested credit renewals.
calls=[]
def estimate(agent):
    calls.append(agent)
    return {'A':F(4),'B':F(6)}[agent]
kind,x=stage_event({},'x','A',1,estimate,size=1,current_request=1)
assert kind=='NEW' and x.credit=={'A':4} and calls==['A']
ok,live,_,_=plan({},'x',x,1)
assert ok
kind,y=stage_event(live,'x','B',7,estimate,size=1,current_request=7)
assert kind=='RESIDENT' and y.credit=={'A':4,'B':6} and calls==['A','B']
live['x']=y
checks['one_actor_event_one_initial_grant']={
    'new_copy_actor_A':{'A':4},'later_B_actual_reuse':{'A':4,'B':6},
    'benefit_evaluation_order':list(calls),'historical_references_bulk_renewed':False}

# After physical rental, A's next request replaces only A's remaining balance.
# B's share remains spent, even though B's previous initial grant was 6.
charge([live['x'],Block(1,{'C':F(5)})])
assert live['x'].credit=={'A':2,'B':3}
calls.clear()
kind,y=stage_event(live,'x','A',2,estimate,size=1,current_request=2)
assert kind=='RESIDENT' and y.credit=={'A':4,'B':3} and calls==['A']
live['x']=y
before=deepcopy(live);calls.clear()
kind,y=stage_event(live,'x','A',2,estimate,size=1,current_request=2)
assert kind=='DUPLICATE' and y is None and not calls and live==before
kind,y=stage_event(live,'x','B',7,estimate,size=1,current_request=8)
assert kind=='STALE' and y is None and not calls and live==before
checks['separate_request_sequences_preserve_other_paid_credit']={
    'after_rent':{'A':2,'B':3},'A_new_request':{'A':4,'B':3},
    'duplicate_and_stale_events':'no value calculation and no ledger change'}

# Events arriving during the initial backup wait; on completion they reread
# the committed ledger, preserving rent already paid by its producer.
calls.clear()
assert stage_event({},'x','B',7,estimate,size=1,current_request=7,busy={'x'})==('WAIT',None)
assert not calls
published={'x':Block(1,{'A':F(3)},requests={'A':1})}
kind,y=stage_event(published,'x','B',7,estimate,size=1,current_request=7)
assert kind=='RESIDENT' and y.credit=={'A':3,'B':6} and calls==['B']
published['x']=y;calls.clear()
assert stage_event(published,'x','A',1,estimate,size=1,current_request=1)==('DUPLICATE',None)
assert not calls
checks['busy_event_replay_uses_published_remaining_balances']={
    'while_busy':'wait without credit grant','after_copy':{'A':3,'B':6},
    'producer_same_request_after_copy':'no refill'}

# A credit proposal is not a lease until saved. A rejected candidate or
# revalidation retry must not leave an already-processed request marker.
calls.clear();live={'old':Block(1,{'C':F(9)})};before=deepcopy(live)
kind,x=stage_event(live,'x','A',5,estimate,size=1,current_request=5)
assert kind=='NEW' and x.requests=={'A':5}
ok,result,_,_=plan(live,'x',x,1)
assert not ok and live==before and 'x' not in live
kind,again=stage_event(live,'x','A',5,estimate,size=1,current_request=5)
assert kind=='NEW' and again.credit=={'A':4}
checks['uncommitted_grant_does_not_consume_request_marker']={
    'rejected_candidate':'no physical ledger or seen-request record',
    'same_request_retry':'eligible to retry from current live state'}

# Moving readiness ahead of valuation eliminates work for an ineligible new
# copy, while preserving immediate renewal of an existing protected copy.
calls.clear()
assert stage_event({},'x','A',6,estimate,size=1,current_request=6,ready=False)==('WAIT',None)
assert not calls
live={'x':Block(1,{'A':F(1),'B':F(3)},pinned=True,requests={'A':5,'B':1})}
kind,x=stage_event(live,'x','A',6,estimate,size=1,current_request=6,ready=False)
assert kind=='RESIDENT' and x.credit=={'A':4,'B':3} and calls==['A']
checks['new_copy_readiness_precedes_value_only_for_new_copies']={
    'unready_new_copy':'wait without valuation or grant',
    'protected_existing_copy':'actor-only renewal still permitted'}

sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def serial(x):
    if isinstance(x,F):return int(x) if x.denominator==1 else str(x)
    raise TypeError(type(x).__name__)
report={
    'status':'PASS','source_sha256':sha(OUT/'algorithm-2-patent-revised.drawio'),
    'check_count':len(checks),'checks':checks,
    'scope':'exact independent-Agent valuation and trial rental design, not serving code',
    'inputs':{'audit_semantics.py':sha(Path(__file__))},
    'not_validated':['cost calibration','runtime integration','concurrent copy and release protocol',
                     'global WCT optimality','competitive ratio','guaranteed idle expiry']}
(OUT/'SEMANTIC_AUDIT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=serial)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2,default=serial))
