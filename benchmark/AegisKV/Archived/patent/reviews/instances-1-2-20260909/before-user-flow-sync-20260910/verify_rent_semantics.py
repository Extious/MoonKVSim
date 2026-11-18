#!/usr/bin/env python3
"""Exact arithmetic checks for the all-block rental design, not runtime tests."""
from fractions import Fraction as F
from html import unescape
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as E

HERE = Path(__file__).resolve().parent
FIGURES = HERE.parents[1] / 'figures/instances-1-2'
source = FIGURES / 'figure-3-slacklandlord.drawio'
cells = {c.get('id'): c for c in E.parse(source).iter('mxCell')}
for cell in cells.values():
    cell.set('value', unescape(cell.get('value', '')))
labels = '\n'.join(c.get('value', '') for c in cells.values())
comments = json.loads((HERE / 'comments.json').read_text())
comment_text = '\n'.join(line for c in comments['comments'] for line in c['lines'])
assert '冻结' not in labels and '冻结' not in comment_text
assert r'\(x\in Q\)' not in cells['settle'].get('value', '')
assert r'H_x\leftarrow L^{\prime}+G_{a,x}/b_x' in cells['initialize'].get('value', '')
assert r'\max(L^{\prime},H_y)<H_x' in cells['choose'].get('value', '')
assert r'L^{\prime}\leftarrow\max(L^{\prime},H_y)' in cells['rent'].get('value', '')
assert r'新尾块 z 以原 \(H_z\) 入 Q' in cells['rent'].get('value', '')
assert r'H_z\leftarrow' not in labels
assert r'H_x\leftarrow' not in cells['publish'].get('value', '')
assert 'abort' not in cells  # Preserve the user's removed failure branch.

def remaining(size, key, rent):
    return size * max(key - rent, F(0))

checks = []
count = 0
for baseline in [F(0), F(2, 3), F(7)]:
    for size in [F(1), F(4)]:
        for credit in [F(0), F(2), F(9)]:
            key = baseline + credit / size
            for delta in [F(0), F(1, 2), F(3), F(12)]:
                expected = max(credit - size * delta, F(0))
                # Queue eligibility does not enter the economic state.
                for eligible in [False, True]:
                    assert remaining(size, key, baseline + delta) == expected
                    count += 1
checks.append({'name': 'keyed_balance_matches_uniform_byte_rent_inside_and_outside_Q', 'cases': count})

count = 0
for rent in [F(0), F(3), F(10)]:
    for candidate in map(F, [0, 2, 4, 10, 13]):
        for victim in map(F, [0, 2, 4, 10, 13]):
            gate = max(rent, victim) < candidate
            assert gate == (remaining(1, candidate, rent) > remaining(1, victim, rent))
            assert max(rent, victim) >= rent
            if gate:
                assert remaining(1, candidate, max(rent, victim)) > 0
                assert remaining(1, victim, max(rent, victim)) == 0
            count += 1
checks.append({'name': 'strict_gate_matches_remaining_density_and_monotone_rent', 'cases': count})

# A non-tail expired before it became releasable; exposing it must not renew it.
rent, old_key, candidate_key = F(12), F(8), F(15)
assert remaining(1, old_key, rent) == 0
assert max(rent, old_key) == rent and max(rent, old_key) < candidate_key
checks.append({'name': 'expired_internal_block_keeps_key_and_does_not_reverse_rent',
               'rent': 12, 'old_key': 8, 'candidate_key': 15, 'rent_after': 12})

# The former H_y < H_x gate would wrongly accept this zero-credit candidate.
candidate_key = rent
assert old_key < candidate_key
assert not max(rent, old_key) < candidate_key
checks.append({'name': 'zero_candidate_cannot_replace_expired_backup', 'status': 'PASS'})

# An internal shared block still pays; only A renews, B keeps its paid-down share.
old_shares = {'A': F(6), 'B': F(4)}
left = remaining(F(1), F(11), F(6))
paid_shares = {a: c * left / sum(old_shares.values()) for a, c in old_shares.items()}
assert paid_shares == {'A': F(3), 'B': F(2)}
paid_shares['A'] = F(4)
assert sum(paid_shares.values()) == 6 and paid_shares['B'] == 2
checks.append({'name': 'internal_shared_block_pays_before_single_Agent_renewal', 'remaining_A': 4, 'remaining_B': 2})

# Asynchronous copy does not reset the historical key or refund subsequent rent.
assert remaining(1, F(15), F(12)) == 3
assert remaining(1, F(15), F(14)) == 1
assert remaining(1, F(15), F(16)) == 0
checks.append({'name': 'pending_copy_continues_rent_without_key_rebase', 'key': 15, 'balances': [3, 1, 0]})

report = {'status': 'PASS', 'evidence_class': 'design_arithmetic_and_diagram_checks',
          'runtime_or_performance_validation': False,
          'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
          'comment_spec_sha256': hashlib.sha256((HERE / 'comments.json').read_bytes()).hexdigest(),
          'checks': checks}
(HERE / 'RENT_CHECKS.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False, indent=2))
