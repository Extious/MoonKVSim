#!/usr/bin/env python3
"""Exact counterexamples for diagram semantics, using existing CPU primitives.

This does not implement the new event paths, allocator or copy protocol.
"""
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import sys

OUT = Path(__file__).resolve().parent
REF = OUT.parent.parent / 'algorithm-2'
sys.path.insert(0, str(REF))
from agent_lease_slacklandlord import CostOracle
from test_agent_lease_slacklandlord import seeded
from test_reference import chain_model
from test_simple_slacklandlord import parallel_model

results = {}

# Total physical benefit is computable without invoking any credit allocator.
m = parallel_model(shared=True)
oracle = CostOracle(m, m.agents)
def allocation_forbidden(*args, **kwargs):
    raise AssertionError('benefit evaluation must not invoke credit allocation')
oracle.shares = allocation_forbidden
gain = oracle.cost(0) - oracle.cost(1)
assert gain == 4
other = parallel_model(shared=True, separate=True)
independent = CostOracle(other, other.agents)
assert independent.cost(0) - independent.cost(1) == 8
results['total_gain_without_credit_allocator'] = {
    'one_shared_workflow': 4, 'two_distinct_workflows': 8,
    'allocator_call_would_fail': True,
}

# Ordered attribution is an accounting convention: each order telescopes to
# the same joint benefit, while Agent grants can differ. Independent gains
# with the other branch unchanged also fail to represent the joint gain.
oracle = CostOracle(m, m.agents)
w = m.workflows['w']
before, after = oracle.prefixes(0), oracle.prefixes(1)
solo = {}
for a in ('a', 'b'):
    state = before.copy()
    state[a] = after[a]
    solo[a] = oracle.workflow_cost(w, before) - oracle.workflow_cost(w, state)
assert solo == {'a': 0, 'b': 0}
forward = oracle.shares(0, 1, 'p')
reverse = {}
state = before.copy()
for a in ('b', 'a'):
    old = oracle.workflow_cost(w, state)
    state[a] = after[a]
    reverse[a] = old - oracle.workflow_cost(w, state)
assert forward == {'a': 0, 'b': 4}
assert reverse == {'b': 0, 'a': 4}
assert sum(forward.values()) == sum(reverse.values()) == gain
results['joint_gain_and_ordered_grants'] = {
    'independent_agent_gains': solo, 'joint_gain': gain,
    'forward_grants': forward, 'reverse_grants': reverse,
    'order_invariance_scope': 'total current gain only; not future renewal policy',
}

# A's new round refills A only; spent B credit stays spent. A second delivery
# of the same round must not refill credit after another physical rent charge.
p = seeded(other, 1)
p.leases['p'].credit = {'a': F(3), 'b': F(1)}
p.new_request('a', 2)
p.refresh_frontier()
assert p.leases['p'].credit == {'a': 4, 'b': 1}
assert p.leases['p'].total == 5 < independent.cost(0)-independent.cost(1)
p.leases['p'].debit(F(1))
spent = deepcopy(p.leases['p'])
assert not p.new_request('a', 2)
p.refresh_frontier()
assert p.leases['p'] == spent
results['one_agent_renewal_preserves_other_spent_credit'] = {
    'current_total_gain': 8, 'after_A_renewal': {'a': 4, 'b': 1},
    'remaining_credit': 5, 'duplicate_round_after_rent': 'no refill',
}

# A paused physical tail retains credit while other blocks advance L. No
# recovery input changed, but its cached key is invalid on re-entry into Q.
p = seeded(other, 1)
p.leases['p'].credit = {'a': F(3), 'b': F(1)}
p.L = F(2)
old_key = p.key('p')
saved, calls = deepcopy(p.leases['p']), p.values.evaluations
p.L = F(9)  # rent paid by other eligible blocks while p was pinned/internal
new_key = p.key('p')
assert (old_key, new_key) == (6, 13)
assert old_key-p.L == -3 and new_key-p.L == 4
assert p.leases['p'] == saved and p.values.evaluations == calls
results['unchanged_value_still_requires_key_rebase'] = {
    'saved_key': 6, 'current_L': 9, 'rebuilt_key': 13,
    'old_key_would_give_negative_rent': -3,
    'credit_unchanged_and_no_WCT_evaluation': True,
}

# The loss of each successive deletion is conditional on the current trial
# prefix, and does not become zero merely because a victim has no credit.
m = chain_model()
oracle = CostOracle(m, m.agents)
gain = oracle.cost(7) - oracle.cost(15)  # add b1 to a1,a2,a3
loss_a3 = oracle.cost(11) - oracle.cost(15)
loss_a2 = oracle.cost(9) - oracle.cost(11)
loss = loss_a3 + loss_a2
assert (gain, loss_a3, loss_a2, loss) == (4, 3, 2, 5)
assert gain-loss == oracle.cost(7)-oracle.cost(9) == -1
results['conditional_deletion_losses_telescope'] = {
    'candidate_gain': gain, 'successive_losses': [loss_a3, loss_a2],
    'D_Y': loss, 'replacement_net': gain-loss,
    'source_of_loss': 'WCT endpoint differences; no Credit input',
}

def serial(value):
    if isinstance(value, F):
        return int(value) if value.denominator == 1 else str(value)
    raise TypeError(type(value).__name__)

sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
report = {
    'status': 'PASS', 'source_sha256': sha(OUT/'algorithm-2-patent-revised.drawio'),
    'checks': results, 'check_count': len(results),
    'inputs': {name: sha(REF/name) for name in [
        'agent_lease_slacklandlord.py', 'test_agent_lease_slacklandlord.py',
        'test_reference.py', 'test_simple_slacklandlord.py', 'reference.py']},
    'scope': 'exact illustrative counterexamples using existing CPU accounting primitives',
    'not_validated': ['new Cache hit runtime integration', 'zero-gain admission runtime',
                      'concurrent allocator or copy protocol', 'measured recovery cost',
                      'optimality or fairness of fixed-ID attribution'],
}
(OUT/'SEMANTIC_AUDIT.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=serial)+'\n')
print(json.dumps(report, ensure_ascii=False, indent=2, default=serial))
