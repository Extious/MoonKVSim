"""Select 4--5 branches with a duration gap within 15 s of 100 s.

Consider all temporally inferred fan-in groups, not just workflow maxima.
Keep longest duration <=250 s. For each candidate choose the midpoint of
the all-active LLM interval nearest the common branch-overlap midpoint.
Require all prefixes in (0,128K]. Among eligible candidates prefer a larger
prefix on the latest-finishing branch, then a gap closer to 100 s. This is
an illustrative selection for visibility of recovery exposure, not an
estimate of population failure impact. The failure-time rule itself does
not optimize outcomes. Cost configuration is unchanged from Figure 2.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from select_motivation_short_example import PINNED_SHA, ROOT, groups

FANIN = ROOT/'benchmark/AegisKV/experiments/data/motivation-fanin-cc'
OUT = ROOT/'benchmark/AegisKV/experiments/data/motivation-compact-cc'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def active_interval(group):
    lo=max(float(b['t']) for b in group)
    hi=min(float(b['t'])+float(b['duration_ms'])/1000 for b in group)
    points={lo,hi}
    for b in group:
        for r in b['requests']:
            start=float(r['t']); end=start+float(r.get('api_time',0))
            if start<hi and end>lo: points.update((max(start,lo),min(end,hi)))
    points=sorted(points); intervals=[]
    for left,right in zip(points,points[1:]):
        mid=(left+right)/2
        active=[[(i,r) for i,r in enumerate(b['requests'])
                 if float(r['t'])<mid<float(r['t'])+float(r.get('api_time',0))] for b in group]
        if all(len(a)==1 for a in active):intervals.append((left,right,[a[0] for a in active]))
    chosen=min(intervals,key=lambda x:(abs((x[0]+x[1])/2-(lo+hi)/2),x[0])) if intervals else None
    return chosen,intervals,lo,hi


def select(trace):
    population=json.loads((FANIN/'SELECTION.json').read_text())
    for p,h in population['files'].items():assert sha(ROOT/p)==h
    audit=json.loads((FANIN/'group-audit.json').read_text())
    candidates=[r for r in audit if r['classification']=='retained_temporal_fanin'
                and 4<=r['fanout_width']<=5 and abs(r['duration_gap_s']-100)<=15
                and r['slowest_duration_s']<=250]
    wanted={r['source_line']:r['source_line_sha256'] for r in candidates}
    workflows={};digest=hashlib.sha256()
    with trace.open('rb') as stream:
        for line_no,raw in enumerate(stream,1):
            digest.update(raw)
            if line_no in wanted:
                assert hashlib.sha256(raw).hexdigest()==wanted[line_no]
                workflows[line_no]=json.loads(raw)
    assert digest.hexdigest()==PINNED_SHA==population['source_sha256']
    comparison=[];eligible=[]
    for evidence in candidates:
        w=workflows[evidence['source_line']]
        segment,begin,group=next(g for g in groups(w['requests']) if g[0]==evidence['fanout_segment_index'])
        chosen,intervals,lo,hi=active_interval(group)
        critical=max(range(len(group)),key=lambda i:float(group[i]['t'])+float(group[i]['duration_ms'])/1000)
        valid=bool(chosen and all(0<int(r['in'])<=131072 for _,r in chosen[2]))
        row=dict(fanout_id=evidence['fanout_id'],branches=len(group),gap_s=evidence['duration_gap_s'],
                 eligible=valid,prefix_tokens=[int(r['in']) for _,r in chosen[2]] if chosen else [],
                 reason='eligible' if valid else 'no common active interval or a prefix exceeds 128K')
        if valid:
            row['critical_prefix_tokens']=int(chosen[2][critical][1]['in'])
            eligible.append((row,w,evidence,segment,begin,group,chosen,intervals,lo,hi))
        comparison.append(row)
    item=min(eligible,key=lambda x:(-x[0]['critical_prefix_tokens'],abs(x[0]['gap_s']-100),x[0]['fanout_id']))
    _,w,evidence,segment,begin,group,chosen,intervals,lo,hi=item
    left,right,active=chosen;failure=round((left+right)/2,1)
    if not left<failure<right:failure=(left+right)/2
    starts=[float(b['t']) for b in group];durations=[float(b['duration_ms'])/1000 for b in group]
    ends=[s+d for s,d in zip(starts,durations)];join=max(ends)
    following=w['requests'][evidence['following_main_index']]
    assert float(following['t'])>=join and all(b['status']=='completed' for b in group)
    output=[];branches=[]
    for i,(branch,(ri,r)) in enumerate(zip(group,active)):
        assert float(r['t'])<failure<float(r['t'])+float(r['api_time'])
        assert int(r['in'])==len(r['hash_ids'])*int(w['block_size'])
        output.append(dict(trace_sha256=PINNED_SHA,workflow_id=w['id'],fanout_id=evidence['fanout_id'],
            fanout_segment_index=segment,fanout_width=len(group),branch_index=i,agent_id=branch['agent_id'],
            branch_start_s=round(starts[i],6),branch_end_s=round(ends[i],6),duration_s=round(durations[i],6),
            slack_s=round(join-ends[i],6),overlap_start_s=lo,overlap_end_s=hi,fanout_completion_s=join,
            failure_time_s=failure,prefix_request_start_s=float(r['t']),prefix_request_api_time_s=float(r['api_time']),
            prefix_tokens=int(r['in']),parallel_definition='max_start_lt_min_end'))
        branches.append(dict(top_level_index=begin+i,branch={k:v for k,v in branch.items() if k!='requests'},
                             prefix_request_index=ri,prefix_request=r))
    OUT.mkdir(parents=True,exist_ok=True);csv_path=OUT/'compact-example-failure-position.csv'
    with csv_path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(output[0]));writer.writeheader();writer.writerows(output)
    excerpt=OUT/'selected-trace-excerpt.json'
    excerpt.write_text(json.dumps(dict(workflow_id=w['id'],source_line=evidence['source_line'],
        source_line_sha256=evidence['source_line_sha256'],block_size=w['block_size'],hash_id_scope=w['hash_id_scope'],
        fanout_segment_index=segment,preceding_main={k:v for k,v in w['requests'][begin-1].items() if k!='hash_ids'},
        following_main={k:v for k,v in following.items() if k!='hash_ids'},following_main_index=evidence['following_main_index'],
        branches=branches),indent=2)+'\n')
    population_rows=list(csv.DictReader((FANIN/'workflow-parallel-gap.csv').open()))
    wf=next(r for r in population_rows if r['workflow_id']==w['id'])
    record=dict(generator=str(Path(__file__).relative_to(ROOT)),generator_sha256=sha(__file__),
        source_path=str(trace),source_sha256=PINNED_SHA,selection_rule=__doc__.strip(),candidate_comparison=comparison,
        target_gap_s=100,target_median_s=population['median_duration_gap_s'],
        selected_duration_gap_s=max(durations)-min(durations),selected_workflow_id=w['id'],
        selected_fanout_segment_index=segment,fanout_width=len(group),selected_duration_range_s=[min(durations),max(durations)],
        selected_prefix_range_tokens=[min(r['prefix_tokens'] for r in output),max(r['prefix_tokens'] for r in output)],
        is_workflow_max=evidence['fanout_id']==wf['selected_fanout_id'],workflow_max_gap_s=float(wf['max_duration_gap_s']),
        failure_time_s=failure,display_time_origin_s=min(starts),failure_time_since_fork_s=failure-min(starts),
        join_time_since_fork_s=join-min(starts),following_main_start_s=float(following['t']),
        all_active_intervals_s=[[x[0],x[1]] for x in intervals],selected_active_interval_s=[left,right],
        files={str(p.relative_to(ROOT)):sha(p) for p in [csv_path,excerpt]},
        source_sha256_by_path={str(p.relative_to(ROOT)):sha(p) for p in [FANIN/'SELECTION.json',FANIN/'workflow-parallel-gap.csv',FANIN/'group-audit.json']},
        evidence_boundary='Illustrative group from the same retained fan-ins, NOT its workflow maximum or an ECDF sample. '
        'Timing-inferred join. Costs use unchanged Qwen3-14B static configuration with an assumed 64-token tail. '
        'Independent single-branch counterfactuals, not original-model measurements or population failure effects.')
    (OUT/'SELECTION.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:record[k] for k in ['selected_workflow_id','fanout_width','selected_duration_gap_s','is_workflow_max','failure_time_since_fork_s','selected_prefix_range_tokens']},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--trace',type=Path,required=True);select(p.parse_args().trace)
