"""Diagnose the preserved equal-byte rental counterexample without publishing.

Mechanism changes, no parameter search: renew a resident after the scored
use is observed; inspect at most two credit-ordered victims; revalue the credit
endowment without refunding rent already paid. The original model and
manuscript are read-only. This does not implement patent Agent ledgers,
prefix dependencies, three tiers, or real serving execution.
"""
from __future__ import annotations
import ast
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).with_name('expanded.py')
OUT = ROOT / 'exports/rental-diagnosis-20260921'
POLICIES = {
    'Direct value': (False, False, 1, False),
    'Original rent': (True, False, 1, False),
    'Rent + scored-hit renewal': (True, True, 1, False),
    'Rent + two victims': (True, False, 2, False),
    'Rent + both changes': (True, True, 2, False),
    'Rent + current-value refresh': (True, False, 1, True),
    'Rent + current-value refresh + two victims': (True, False, 2, True),
}


def replay(rental, renew_use, limit, refresh_value, *, phase=0, period=18, slots=8):
    resident = set(range(slots))
    rho = 0.0
    keys = {i: 2.0 + (i % 3) * .2 for i in resident}
    miss = movement = 0.0
    migrations = revalues = scored_hits = 0
    rejected_with_better_victim = higher_value_victims = 0
    last_values = None
    credit_refreshes = 0
    events = []
    for step in range(512):
        tick = step + phase
        values = {i: 1.5 + .8 * math.sin(tick / period + i * .63)
                  + .35 * (i // 8 == (tick // 64) % 3) for i in range(24)}
        if refresh_value and last_values is not None:
            for obj in resident:
                # H = origin + current endowment. Changing the endowment does
                # not reset origin to rho or refund rent paid since renewal.
                old_origin = keys[obj] - last_values[obj]
                keys[obj] += values[obj] - last_values[obj]
                assert abs((keys[obj] - values[obj]) - old_origin) < 1e-9
                credit_refreshes += 1
        candidate = (tick * 7) % 24
        old_rent = rho
        record = dict(step=step, candidate=candidate, candidate_hit=candidate in resident,
                      checks=0, moved=False, victim='', avoidable_rejection=False)
        if candidate in resident:
            keys[candidate] = rho + values[candidate]
        else:
            order = sorted(resident, key=lambda i: (keys[i], i))[:limit] if rental else [
                min(resident, key=lambda i: (values[i], i))]
            feasible = []
            for victim in order:
                trial = max(rho, keys[victim]) if rental else rho
                allowed = rho + values[candidate] > trial + 1e-12 if rental else True
                if allowed:
                    revalues += 1
                    record['checks'] += 1
                    gain = values[candidate] - values[victim]
                    if gain > .2 + .1:
                        feasible.append((gain, -victim, victim, trial))
            if feasible:
                _, _, victim, trial = max(feasible)
                best = min(resident, key=lambda i: (values[i], i))
                higher_value_victims += int(values[victim] > values[best] + 1e-12)
                resident.remove(victim)
                resident.add(candidate)
                keys.pop(victim)
                rho = trial
                keys[candidate] = rho + values[candidate]
                migrations += 1
                movement += .1
                record.update(moved=True, victim=victim)
            else:
                # Read-only diagnosis, never consulted by the policy.
                record['avoidable_rejection'] = any(
                    values[candidate] - values[v] > .2 + .1 for v in resident)
                rejected_with_better_victim += int(record['avoidable_rejection'])
        # Reveal the scored use only after the placement decision. Do not peek.
        request = (tick * 11 + tick // 64) % 24
        hit = request in resident
        if hit:
            scored_hits += 1
            if renew_use:
                keys[request] = rho + values[request]
        else:
            miss += values[request]
        assert len(resident) == slots
        assert rho >= old_rent
        if not record['moved']:
            assert rho == old_rent
        assert abs(movement - .1 * migrations) < 1e-9
        record.update(request=request, request_hit=hit, miss=miss, movement=movement,
                      rent=rho, migrations=migrations, revalues=revalues)
        events.append(record)
        last_values = values
    result = dict(miss=miss, movement=movement, total=miss+movement,
                  migrations=migrations, revalues=revalues, scored_hits=scored_hits,
                  credit_refreshes=credit_refreshes,
                  rejected_with_better_victim=rejected_with_better_victim,
                  higher_value_victims=higher_value_victims)
    return result, events


def write_csv(path, rows):
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    raw_source = SOURCE.read_text()
    node = next(n for n in ast.parse(raw_source).body
                if isinstance(n, ast.FunctionDef) and n.name == 'rental_stream')
    namespace = {'math': math}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    # Exact reproduction, without importing the module or regenerating any data.
    for rental, policy in [(False, 'Direct value'), (True, 'Original rent')]:
        old = namespace['rental_stream'](rental)
        _, got = replay(*POLICIES[policy])
        for before, after in zip(old, got, strict=True):
            for key in ['miss', 'movement', 'migrations', 'revalues', 'rent']:
                assert abs(before[key] - after[key]) < 1e-10, (policy, key)
    base, events = {}, []
    for name, args in POLICIES.items():
        base[name], trace = replay(*args)
        events.extend(dict(policy=name, **row) for row in trace)
    # Declared sensitivity grid, not independent workload trials or a tuning set.
    grid = []
    for phase, period, slots in itertools.product([0, 32, 96, 192], [9, 18, 36], [4, 8, 12]):
        for name, args in POLICIES.items():
            result, _ = replay(*args, phase=phase, period=period, slots=slots)
            grid.append(dict(phase=phase, period=period, slots=slots, policy=name, **result))
    paired = {}
    for name in POLICIES:
        differences, vs_original = [], []
        for row in [x for x in grid if x['policy'] == name]:
            match = lambda x: all(x[k] == row[k] for k in ['phase', 'period', 'slots'])
            direct = next(x for x in grid if x['policy'] == 'Direct value' and match(x))
            original = next(x for x in grid if x['policy'] == 'Original rent' and match(x))
            differences.append(row['total'] - direct['total'])
            vs_original.append(row['total'] - original['total'])
        paired[name] = dict(
            cases=len(differences), mean_cost_delta_vs_direct=sum(differences)/len(differences),
            wins_vs_direct=sum(d < -1e-9 for d in differences),
            losses_vs_direct=sum(d > 1e-9 for d in differences),
            mean_cost_delta_vs_original=sum(vs_original)/len(vs_original),
            wins_vs_original=sum(d < -1e-9 for d in vs_original),
            losses_vs_original=sum(d > 1e-9 for d in vs_original))
    result = dict(evidence='deterministic isolated model diagnosis; no physical measurements',
                  source=str(SOURCE), source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                  generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  base=base, sensitivity=paired,
                  limitations=['Same synthetic candidate/use streams and additive drifting values.',
                               'Scored misses are served transiently; only candidate events admit objects.',
                               'Initial keys retain the original arbitrary warm-start values.',
                               'No Agent shares, prefix dependency, Slack, multi-tier queues or measured CPU cost.',
                               'Read-only diagnostic oracle checks are excluded from controller counters.',
                               'Value refresh eagerly updates every resident key; this is not a low-overhead implementation.',
                               'Victim scans/sorts and shared value generation are not counted by revalues.',
                               'Top-two screen increases value comparisons; no universal improvement claim.'])
    (OUT/'RESULTS.json').write_text(json.dumps(result, indent=2)+'\n')
    write_csv(OUT/'base-events.csv', events)
    write_csv(OUT/'sensitivity.csv', grid)
    print(json.dumps(dict(base=base, sensitivity=paired), indent=2))


if __name__ == '__main__':
    main()
