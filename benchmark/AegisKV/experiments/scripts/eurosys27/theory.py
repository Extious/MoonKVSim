#!/usr/bin/env python3
"""Deterministic DRAM/storage scenario model, never a serving-system benchmark.

No experimental speedups are inputs. The shared-resource scheduler derives
restore times from bytes, service rates, dependencies, and declared ordering.
Static policy comparisons use whole checkpoint groups, exact residual joins,
and a finite byte budget. They do not execute the asynchronous implementation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "experiments/eurosys27/config.json"
OUT = ROOT / "experiments/data/eurosys27/theory"


@dataclass(frozen=True)
class Group:
    name: str
    gib: float
    remaining: float
    reuse: float


def _restore_impl(groups, resident, cfg, recompute=False):
    """Event calendar: read -> shared NIC -> target H2D -> tail compute.

    Equal 0.25 GiB chunks are submitted in chunk-major, request-ID order.
    Ready operations use earliest feasible start, then submission ID. There
    is one DRAM channel, one storage channel, one shared NIC, and separate
    H2D / compute engines on each of two targets. All data are required before
    a request's tail replay. Chunk transport overlaps; layer compute does not.
    """
    if not groups:
        return []
    tasks, children = [], {}
    outstanding = [0] * len(groups)
    ends = [cfg["floor_s"]] * len(groups)
    free, ready, result = {}, [], [None] * len(groups)

    def add(resource, duration, release, owner, parent=None, final=False):
        k = len(tasks)
        tasks.append((resource, duration, owner, final))
        if parent is None:
            ready.append((k, release))
        else:
            children.setdefault(parent, []).append(k)
        return k

    if recompute:
        # Bounded 0.25 GiB reconstruction quanta, with a dependency per request.
        prior = [None] * len(groups)
        count = [math.ceil(g.gib / cfg["chunk_GiB"]) for g in groups]
        for c in range(max(count)):
            for i, g in enumerate(groups):
                if c >= count[i]:
                    continue
                b = min(cfg["chunk_GiB"], g.gib-c*cfg["chunk_GiB"])
                prior[i] = add(f"compute{i % cfg['recovery_targets']}",
                    b*cfg["recompute_s_per_GiB"], cfg["floor_s"], i, prior[i])
        for i in range(len(groups)):
            add(f"compute{i % cfg['recovery_targets']}", cfg["replay_s"],
                cfg["floor_s"], i, prior[i], True)
    else:
        count = [math.ceil(g.gib / cfg["chunk_GiB"]) for g in groups]
        outstanding[:] = count
        for c in range(max(count)):
            for i, g in enumerate(groups):
                if c >= count[i]:
                    continue
                b = min(cfg["chunk_GiB"], g.gib-c*cfg["chunk_GiB"])
                tier = "dram" if i in resident else "storage"
                a = add(tier, b / cfg[tier+"_read_GiB_s"], cfg["floor_s"], i)
                a = add("nic", b/cfg["shared_link_GiB_s"], 0, i, a)
                add(f"h2d{i % cfg['recovery_targets']}", b/cfg["h2d_GiB_s"], 0, i, a, True)
    while ready:
        pos = min(range(len(ready)), key=lambda p: (
            max(ready[p][1], free.get(tasks[ready[p][0]][0], 0)), ready[p][0]))
        k, release = ready.pop(pos)
        resource, duration, owner, final = tasks[k]
        stop = max(release, free.get(resource, 0)) + duration
        free[resource] = stop
        for child in children.get(k, []):
            ready.append((child, stop))
        if final:
            if recompute or resource.startswith("compute"):
                result[owner] = stop
            else:
                ends[owner] = max(ends[owner], stop)
                outstanding[owner] -= 1
                if outstanding[owner] == 0:
                    add(f"compute{owner % cfg['recovery_targets']}", cfg["replay_s"],
                        ends[owner], owner, final=True)
    assert all(x is not None for x in result)
    return result


@lru_cache(maxsize=16000)
def _cached_restore(groups, resident, settings, recompute):
    return tuple(_restore_impl(groups, resident, dict(settings), recompute))


def restore(groups, resident, cfg, recompute=False):
    keys = ['floor_s','chunk_GiB','recovery_targets','recompute_s_per_GiB',
            'replay_s','dram_read_GiB_s','storage_read_GiB_s','shared_link_GiB_s','h2d_GiB_s']
    return _cached_restore(tuple(groups), frozenset(resident),
                           tuple((k,cfg[k]) for k in keys), recompute)


def loss(groups, times):
    """Common-source fault at a fork: replay all affected branches together."""
    return max(g.remaining+t for g, t in zip(groups, times))-max(g.remaining for g in groups)


def objective(groups, resident, cfg):
    # Mutually exclusive, conditional next-use identity; reuse weight is the
    # probability of a next-use episode in H, separate from fault probability.
    ptotal = sum(g.reuse for g in groups)
    normal = sum(g.reuse/ptotal * restore([g], {0} if i in resident else set(), cfg)[0]
                 for i, g in enumerate(groups)) if ptotal else 0
    fault = loss(groups, restore(groups, resident, cfg))
    return cfg.get("reuse_episode_probability", .02)*normal + cfg["default_failure_probability_per_horizon"]*fault


def choose(groups, budget, cfg, policy="AegisKV model", prediction_error=0):
    if policy == "Storage only" or policy == "Recompute":
        return set()
    if policy == "All DRAM":
        return set(range(len(groups)))
    used, chosen = 0., set()
    if policy in ("LRU", "Reuse only"):
        if policy == "LRU":
            order = list(reversed(range(len(groups))))  # declared recency trace
        else:
            order = sorted(range(len(groups)), key=lambda i: (-groups[i].reuse, i))
        for i in order:
            if used + groups[i].gib <= budget + 1e-9:
                chosen.add(i); used += groups[i].gib
        return chosen
    if policy == "Feasible oracle":
        candidates = [set(i for i in range(len(groups)) if mask & (1 << i))
                      for mask in range(1 << len(groups))]
        candidates = [s for s in candidates if sum(groups[i].gib for i in s) <= budget+1e-9]
        return min(candidates, key=lambda s: (objective(groups, s, cfg), sum(groups[i].gib for i in s), sorted(s)))
    estimated = [replace(g, remaining=max(.01, g.remaining *
                    (1+prediction_error*(1 if i % 2 else -1)))) for i, g in enumerate(groups)]
    if policy == "No dependencies":
        estimated = [replace(g, remaining=1.) for g in groups]
    local_cfg = dict(cfg)
    if policy == "No reuse value":
        local_cfg["reuse_episode_probability"] = 0
    while True:
        before = objective(estimated, chosen, local_cfg)
        candidates = []
        for i, g in enumerate(groups):
            if i in chosen or used+g.gib > budget+1e-9:
                continue
            gain = before-objective(estimated, chosen | {i}, local_cfg)
            candidates.append((gain/g.gib, gain, -i, i))
        if not candidates:
            break
        _, gain, _, i = max(candidates)
        if gain <= 1e-12:
            break
        chosen.add(i); used += groups[i].gib
    return chosen


class Dataset:
    def __init__(self):
        self.rows = []

    def add(self, figure, panel, series, x, y, unit, scenario="base", **extra):
        self.rows.append(dict(figure=figure, panel=panel, series=series, x=x, y=y,
            lower="", upper="", unit=unit, evidence="analytical", scenario_id=scenario,
            source_id="declared-model-v1", independent_runs=0, **extra))

    def write(self, out):
        out.mkdir(parents=True, exist_ok=True)
        for figure in sorted(set(r["figure"] for r in self.rows)):
            rows = [r for r in self.rows if r["figure"] == figure]
            path = out/(figure+".csv")
            with path.open("w", newline="") as f:
                w=csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)


def generate(cfg, out):
    ds = Dataset()
    groups = [Group(f"A{i}", b, d, q) for i, (b,d,q) in enumerate(zip(
        cfg["default_group_GiB"],cfg["default_remaining_s"],cfg["normal_reuse_probability"]))]
    policies = ["Storage only", "LRU", "Reuse only", "AegisKV model", "Feasible oracle"]
    records = []
    # 36 deterministic scenarios; no stochastic repetitions or confidence intervals.
    for size, slack, bw in itertools.product([.5,1,2], [0,.3,1,3], [1,4,12]):
        c = dict(cfg, storage_read_GiB_s=bw)
        gs = [replace(g, gib=g.gib*size, remaining=12-(12-g.remaining)*slack) for g in groups]
        # Negative remaining durations are avoided without altering the slack differences.
        lo = min(g.remaining for g in gs)
        gs = [replace(g, remaining=g.remaining-min(0,lo)+1) for g in gs]
        sid=f"size{size}-slack{slack}-storage{bw}"
        for pol in policies:
            resident=choose(gs,16*size,c,pol)
            value=loss(gs,restore(gs,resident,c))
            records.append(dict(scenario_id=sid,policy=pol,dram_GiB=16*size,
                state_GiB=sum(g.gib for g in gs),storage_GiB_s=bw,slack_scale=slack,
                failure_penalty_s=value,objective_s=objective(gs,resident,c),
                resident_groups=":".join(map(str,sorted(resident)))))
    for pol in policies:
        vals=sorted(r["failure_penalty_s"] for r in records if r["policy"]==pol)
        for i,value in enumerate(vals):
            ds.add("workflow-outcomes","cdf",pol,value,(i+1)/len(vals),"fraction",f"rank{i+1}")
    # Capacity sweep and a dimensionless causal comparison under fixed 40 GiB state.
    for budget in [0,4,8,12,16,20,24,28,32,36,40]:
        for pol in policies[1:]:
            resident=choose(groups,budget,cfg,pol)
            ds.add("capacity-frontier","budget",pol,budget,loss(groups,restore(groups,resident,cfg)),"s")
    for bw in [.5,1,2,4,8,12,20]:
        c=dict(cfg,storage_read_GiB_s=bw)
        for pol in ["Storage only","LRU","AegisKV model","All DRAM"]:
            resident=choose(groups,16,c,pol)
            ds.add("storage-bottleneck","bandwidth",pol,bw,loss(groups,restore(groups,resident,c)),"s")
    # Ablation: paired scenarios, means with no inferential intervals.
    ablations=["LRU","Reuse only","No dependencies","No reuse value","AegisKV model","Feasible oracle"]
    for pol in ablations:
        vals=[]; normal=[]
        for size, slack in itertools.product([.5,1,2],[0,.3,1,3]):
            gs=[replace(g,gib=g.gib*size,remaining=40-(12-g.remaining)*slack) for g in groups]
            resident=choose(gs,16*size,cfg,pol)
            vals.append(loss(gs,restore(gs,resident,cfg)))
            normal.append(sum(g.reuse*restore([g],{0} if i in resident else set(),cfg)[0]
                              for i,g in enumerate(gs))/sum(g.reuse for g in gs))
        ds.add("policy-ablation","fault",pol,ablations.index(pol),sum(vals)/len(vals),"s","12-scenarios")
        ds.add("policy-ablation","reuse",pol,ablations.index(pol),sum(normal)/len(normal),"s","12-scenarios")
    # Signed errors affect placement, while true remaining durations determine outcomes.
    for error in [-1,-.75,-.5,-.25,0,.25,.5,.75,1]:
        for pol in ["LRU","AegisKV model","Feasible oracle"]:
            resident=choose(groups,16,cfg,pol,error)
            ds.add("prediction-robustness","error",pol,error*100,
                   loss(groups,restore(groups,resident,cfg)),"s")
    # Checkpoint phases: same commit frontier, replay of a declared ideal uniform phase.
    # Writeback lag is separate; the decision trigger does not imply durability.
    for z in [64,256,1024]:
        for lag in [0,.25,.5,1,2,4]:
            # 100 token/s generation, 2.5 ms/token replay; averaged exactly over N=0..Z-1.
            replay=sum((n+100*lag)*.0025 for n in range(z))/z
            c=dict(cfg,replay_s=replay)
            resident=choose(groups,16,c, "AegisKV model")
            ds.add("checkpoint-lag","lag",f"Z = {z}",lag,loss(groups,restore(groups,resident,c)),"s")
    # Explicit queue model for healthy I/O sharing. It is not measured TTFT.
    for backup in [0,.05,.10,.15,.20,.25,.30]:
        for load in [.3,.5,.7]:
            util=load+backup
            if util>=1: continue
            # M/D/1 mean queue+service, 10 ms service quanta, independent Poisson arrivals.
            latency=.010*(1+util/(2*(1-util)))
            ds.add("healthy-io","load",f"Foreground {int(load*100)}%",backup*100,latency*1000,"ms")
    # A transient occupancy accounting example: 8 GiB migration at 2 GiB/s.
    # Payload frees only after all copy+commit+reader draining; budget is a target.
    for t in [0,1,2,3,4,4.5,5,5.5,6,7,8]:
        copied=min(8,2*max(0,t-1))
        physical=24 if t<5.5 else 16
        ds.add("safe-demotion","occupancy","Physical DRAM",t,physical,"GiB")
        ds.add("safe-demotion","occupancy","DRAM target",t,16 if t>=1 else 24,"GiB")
        ds.add("safe-demotion","copied","Storage copy",t,copied,"GiB")
    # Joint failure counterexample: local slack can undervalue a correlated group.
    # Two critical branches: one local improvement cannot advance the join.
    for n in [0,1,2]:
        individual=2*(10)-n*8
        joint=10 if n<2 else 2
        ds.add("common-fault","counterexample","Sum of local penalties",n,individual,"s")
        ds.add("common-fault","counterexample","Workflow penalty",n,joint,"s")
    # Explicit operation-cost assumption, not a benchmark of controller code.
    for nodes in [10,30,100,300,1000,3000,10000]:
        for candidates in [16,64,256]:
            visits=2*nodes*candidates*8  # two DAG passes, eight profile episodes
            cost_ms=visits*cfg.get('assumed_node_visit_us',.2)/1000
            ds.add('controller-scaling','scaling',f'{candidates} candidates',nodes,cost_ms,'ms')
    ds.write(out)
    with (out/"scenario-results.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
    by={p:{r['scenario_id']:r for r in records if r['policy']==p} for p in policies}
    diffs=[by['LRU'][k]['failure_penalty_s']-v['failure_penalty_s'] for k,v in by['AegisKV model'].items()]
    regrets=[v['objective_s']-by['Feasible oracle'][k]['objective_s'] for k,v in by['AegisKV model'].items()]
    summary={'evidence':'analytical_scenario','independent_physical_runs':0,
      'scenario_count':36,'policy_count':len(policies),'rows':len(ds.rows),
      'mean_fault_penalty_s':{p:sum(r['failure_penalty_s'] for r in by[p].values())/36 for p in policies},
      'vs_lru_s':{'better':sum(d>1e-9 for d in diffs),'tied':sum(abs(d)<=1e-9 for d in diffs),'worse':sum(d< -1e-9 for d in diffs),
                   'minimum_paired_saving':min(diffs),'maximum_paired_saving':max(diffs)},
      'max_objective_regret_s':max(regrets),
      'parameters':cfg,
      'limits':['Generic assumed rates, not hardware calibration.','Static group admission, not the online controller.',
                'Four-branch forks, no multi-workflow steady-state serving.',
                'All selected copies complete before failure; separate lag and demotion examples do not close this gap.',
                'No native model, transport, filesystem, failure injection, or runtime predictor is executed.']}
    (out/"summary.json").write_text(json.dumps(summary,indent=2)+'\n')
    manifest={'schema_version':1,'evidence':'analytical','source_files':{
        'declared-model-v1':{'paths':[str(CONFIG.relative_to(ROOT)),str(Path(__file__).relative_to(ROOT))],
         'sha256':[hashlib.sha256(p.read_bytes()).hexdigest() for p in [CONFIG,Path(__file__)]]}},
        'tables':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob('*.csv'))}}
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2)+'\n')
    return summary


def self_check(cfg):
    g=[Group('a',4,12,.5),Group('b',8,8,.5)]
    assert loss(g,[0,0])==0
    assert loss([Group('a',4,10,1),Group('b',4,1,1)],[0,5])==0
    assert abs(loss([Group('a',4,10,1),Group('b',4,10,1)],[2,10])-10)<1e-9
    assert sum(g[i].gib for i in choose(g,8,cfg))<=8
    # Whole-state analytical endpoints and resource bounds.
    for gs in [g,g[:1]]:
        a=restore(gs,set(range(len(gs))),cfg)
        b=restore(gs,set(),cfg)
        assert max(a)<=max(b)+1e-9
        assert max(b)>=sum(x.gib for x in gs)/cfg['storage_read_GiB_s']
    s=choose(g,8,cfg,'Feasible oracle')
    assert objective(g,s,cfg)<=objective(g,choose(g,8,cfg),cfg)+1e-9


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config',type=Path,default=CONFIG)
    ap.add_argument('--output',type=Path,default=OUT)
    args=ap.parse_args()
    cfg=json.loads(args.config.read_text());self_check(cfg)
    summary=generate(cfg,args.output)
    print(json.dumps({k:summary[k] for k in ['scenario_count','rows','mean_fault_penalty_s','vs_lru_s','max_objective_regret_s']},indent=2))


if __name__=='__main__':
    main()
