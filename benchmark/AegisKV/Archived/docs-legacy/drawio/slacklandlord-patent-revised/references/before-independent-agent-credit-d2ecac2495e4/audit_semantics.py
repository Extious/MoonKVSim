#!/usr/bin/env python3
"""Exact counterexamples for the unified rental DESIGN, not a serving runtime.

The small ledger below exercises the diagram's new event contract. Existing
CPU CostOracle is used only to evaluate WCT; its earlier event policy is not run.
"""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import hashlib,json,sys
from pathlib import Path

OUT=Path(__file__).resolve().parent
REF=OUT.parent.parent/'algorithm-2'
sys.path.insert(0,str(REF))
from agent_lease_slacklandlord import CostOracle,Lease
from reference import Model
from test_reference import chain_model,slack_model
from test_simple_slacklandlord import parallel_model


def prefix_pair(model,mask,key):
    """Value x as the END of its usable prefix; omit its backed-up descendants.

    Other branches remain at the current frontier. This makes an internal
    cache-hit value defined without allowing illegal holes in a backup prefix.
    """
    idx=model.index[key]
    with_x=mask|(1<<idx)
    for i in range(len(model.chunks)):
        if model.ancestors[i] & (1<<idx):with_x &= ~(1<<i)
    without=with_x & ~(1<<idx)
    assert model.legal(with_x) and model.legal(without)
    return without,with_x


def value_and_grants(model,mask,key):
    oracle=CostOracle(model,model.agents)
    without,with_x=prefix_pair(model,mask,key)
    gain=oracle.cost(without)-oracle.cost(with_x)
    grants=oracle.shares(without,with_x,key)
    assert sum(grants.values())==gain
    return gain,grants


def refresh(lease,grants,rounds,*,reused=(),new_copy=False):
    """Only a new physical copy or an actual unprocessed reuse grants credit."""
    for a,grant in grants.items():
        old_round=lease.seen_round.get(a,-1)
        if a in reused and rounds[a]<old_round:raise ValueError('stale request')
        authorized=new_copy or (a in reused and rounds[a]>old_round)
        lease.credit[a]=grant if authorized else min(lease.credit.get(a,F(0)),grant)
        if authorized:lease.seen_round[a]=rounds[a]


def charge(leases,sizes,eligible):
    """One physical rent amount, proportional sublease debit, no H or L."""
    delta=min(leases[y].total/sizes[y] for y in eligible)
    for y in eligible:leases[y].debit(sizes[y]*delta)
    return delta


def gate(gain,loss,evictions):
    return gain>=0 if not evictions else gain>loss


checks={}
# Joint total gain is independent of the credit allocator. Shared branches in
# the same workflow cannot be treated as two independent WCT improvements.
m=parallel_model(shared=True);o=CostOracle(m,m.agents)
def forbidden(*args):raise AssertionError('allocation used during gain evaluation')
o.shares=forbidden
assert o.cost(0)-o.cost(1)==4
separate=parallel_model(shared=True,separate=True);v=CostOracle(separate,separate.agents)
assert v.cost(0)-v.cost(1)==8
checks['joint_gain_before_allocation']={'one_shared_workflow':4,'two_workflows':8,'gain_calls_no_allocator':True}

# Slack is an actual input to grant renewal, in both directions. An already
# paid balance is reset only by the reusing Agent's next request.
l=Lease({'a':F(1)},{'a':1})
for round_id,slack,expected in [(2,10,2),(3,13,0),(4,0,4)]:
    m=slack_model(slack);g,w=value_and_grants(m,1,'a')
    assert g==expected
    refresh(l,w,{'a':round_id,'b':1},reused={'a'})
    assert l.credit['a']==expected
checks['reuse_renews_from_new_Slack']={'slacks':[10,13,0],'new_credit':[2,0,4]}

# A's renewal does not refund B, even though their present grant caps are 4/4.
g,w=value_and_grants(separate,1,'p')
l=Lease({'a':F(3),'b':F(1)},{'a':1,'b':1})
refresh(l,w,{'a':2,'b':1},reused={'a'})
assert l.credit=={'a':4,'b':1} and l.total==5<g
l.debit(F(1));saved=deepcopy(l)
refresh(l,w,{'a':2,'b':1},reused={'a'})
assert l==saved
try:refresh(l,w,{'a':1,'b':1},reused={'a'})
except ValueError:pass
else:raise AssertionError('old request renewed')
checks['shared_renewal_and_duplicate_delivery']={'new_grants':w,'A_only_result':{'a':4,'b':1},'duplicate_after_rent':'no refill','old_request':'rejected'}

# A new Agent round WITHOUT actual reuse cannot refill y during queue revalue.
l=Lease({'a':F(1),'b':F(1)},{'a':1,'b':1})
refresh(l,w,{'a':9,'b':1})
assert l.credit=={'a':1,'b':1} and l.seen_round=={'a':1,'b':1}
checks['queue_revalue_never_consumes_unseen_round']={'balance':l.credit,'recorded_rounds':l.seen_round}

# An internal block is refreshed immediately; no tail eligibility condition
# is necessary for credit renewal. Its descendants remain physically backed up.
m=chain_model();mask=7
assert prefix_pair(m,mask,'a1')==(0,1)
g,wroot=value_and_grants(m,mask,'a1');assert g==1
root=Lease({'a':F(1,2)},{'a':1})
refresh(root,wroot,{'a':2,'b':1},reused={'a'})
assert root.credit['a']==1 and root.seen_round['a']==2 and mask==7
# Paused internal credit pays no rent until it becomes an eligible tail.
leases={'root':root,'tail':Lease({'a':F(3)},{'a':1})};saved=deepcopy(root)
assert charge(leases,{'root':1,'tail':1},['tail'])==3
assert root==saved and leases['tail'].total==0
checks['internal_hit_immediate_and_rent_excluded']={'prefix_pair':[0,1],'old_credit':'1/2','renewed_credit':1,'physical_mask_unchanged':7,'internal_credit_after_tail_rent':1}

# Variable physical sizes and shared tenants: one charge per physical block.
leases={'shared':Lease({'a':F(3),'b':F(5)},{}),'other':Lease({'c':F(3)},{}),'zero':Lease({'d':F(0)},{})}
sizes={'shared':4,'other':3,'zero':2}
assert charge(leases,sizes,['shared','other'])==1
assert leases['shared'].credit=={'a':F(3,2),'b':F(5,2)}
assert leases['shared'].total==4 and leases['other'].total==0
saved=deepcopy(leases)
assert charge(leases,sizes,['shared','zero'])==0 and leases==saved
checks['physical_rent_and_zero_balance']={'delta':1,'shared_physical_bytes':4,'shared_charge':4,'remaining_subleases':leases['shared'].credit,'zero_credit_no_division_error':True}

# Admission must use conditional losses, not the victim's remaining credit.
m=chain_model();o=CostOracle(m,m.agents)
gain=o.cost(7)-o.cost(15)
losses=[o.cost(11)-o.cost(15),o.cost(9)-o.cost(11)]
assert (gain,losses)==(4,[3,2])
assert gain-sum(losses)==o.cost(7)-o.cost(9)==-1
assert not gate(gain,sum(losses),['a3','a2'])
assert gate(0,0,[]) and not gate(0,0,['old'])
assert not gate(4,4,['old']) and gate(4,3,['old'])
checks['piecewise_gate_and_conditional_deletion']={'gain':gain,'successive_losses':losses,'net':-1,'zero_gain_free_space':True,'zero_or_tied_replacement':False}

# Rent calculations staged in a failed trial do not leak into live balances.
live={'a':Lease({'a':F(4)},{'a':1}),'b':Lease({'b':F(2)},{'b':1})}
snapshot=deepcopy(live);trial=deepcopy(live)
charge(trial,{'a':1,'b':1},['a','b'])
assert trial!=live and live==snapshot
checks['failed_trial_keeps_live_balances']={'isolated_ledger':True}

# The single-Agent shortcut equals the fixed-path WCT improvement, including
# the zero-gain part below Slack. These are illustrative costs, not measurements.
for before,after in [(7,3),(16,13)]:
    for slack in range(22):
        assert min(before-after,max(before-slack,0))==max(before-slack,0)-max(after-slack,0)
checks['single_Agent_Slack_identity']={'cases':44,'scope':'one workflow, one changing recovery node; other paths fixed'}

sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def serial(x):
    if isinstance(x,F):return int(x) if x.denominator==1 else str(x)
    raise TypeError(type(x).__name__)
report={'status':'PASS','source_sha256':sha(OUT/'algorithm-2-patent-revised.drawio'),'check_count':len(checks),'checks':checks,'scope':'exact design-level event/accounting counterexamples, not a runtime implementation','inputs':{name:sha(REF/name) for name in ['agent_lease_slacklandlord.py','reference.py','test_reference.py','test_simple_slacklandlord.py']},'not_validated':['serving integration','concurrent copy protocol','future request activity','cost calibration','global optimality or fairness of fixed-ID attribution']}
(OUT/'SEMANTIC_AUDIT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=serial)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2,default=serial))
