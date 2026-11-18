#!/usr/bin/env python3
"""Independently reconstruct the historical observed statistics from raw JSONL.

No SGLSim or AIConfigurator imports. The five historical latency predictions
remain labeled counterfactual inputs; their arithmetic is checked separately.
"""
import argparse, csv, hashlib, json
from pathlib import Path
from figure_style import PAPER, sha
from paper_paths import DATA, TOOLS, DOCS, BUILD, DELIVERY, TEMPLATE, ARTIFACTS

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--trace',type=Path,required=True);a=p.parse_args()
    dat=DATA/'motivation-real-cc'
    observed=list(csv.DictReader((dat/'real-cc-workflow-parallel-gap.csv').open()))
    examples=list(csv.DictReader((dat/'real-cc-example-failure-position.csv').open()))
    expected={r['workflow_id']:float(r['max_duration_gap_s']) for r in observed}
    actual={}; example_checks=[]; sessions=0; h=hashlib.sha256()
    with a.trace.open('rb') as stream:
        for line in stream:
            h.update(line)
            if not line.strip():continue
            workflow=json.loads(line);sessions+=1;requests=workflow.get('requests',[])
            i=0;gaps=[]
            while i<len(requests):
                if requests[i].get('type')!='subagent':i+=1;continue
                group=[]
                while i<len(requests) and requests[i].get('type')=='subagent':
                    group.append(requests[i]);i+=1
                if len(group)<2:continue
                times=[(float(r.get('t',0)),float(r.get('duration_ms',0))/1000) for r in group]
                if any(duration<=0 for start,duration in times):continue
                if max(start for start,duration in times)>=min(start+duration for start,duration in times):continue
                gaps.append(max(duration for start,duration in times)-min(duration for start,duration in times))
            if gaps:actual[str(workflow['id'])]=max(gaps)
            if str(workflow['id'])==examples[0]['workflow_id']:
                for row in examples:
                    matches=[r for r in requests if r.get('type')=='subagent' and str(r.get('agent_id'))==row['agent_id']]
                    assert len(matches)==1
                    branch=matches[0];start=float(branch['t']);duration=float(branch['duration_ms'])/1000
                    assert abs(start-float(row['branch_start_s']))<1e-6
                    assert abs(duration-float(row['duration_s']))<1e-6
                    assert abs(start+duration-float(row['branch_end_s']))<1e-6
                    nested=max((r for r in branch['requests'] if float(r['t'])<=float(row['failure_time_s']) and int(r.get('in',0))>0),key=lambda r:float(r['t']))
                    assert int(nested['in'])==int(row['prefix_tokens'])
                    assert abs(float(nested['t'])-float(row['prefix_request_start_s']))<1e-6
                    slack=float(row['fanout_completion_s'])-(start+duration)
                    assert abs(slack-float(row['slack_s']))<1e-6
                    assert abs(max(0,float(row['recompute_s'])-slack)-float(row['delta_wct_s']))<1e-6
                    example_checks.append(dict(branch_index=int(row['branch_index']),agent_id=row['agent_id'],timestamp_and_duration_match=True,nested_prefix_match=True,slack_and_exposed_delay_arithmetic_match=True))
    assert set(expected)==set(actual),(len(expected),len(actual))
    error=max(abs(actual[k]-expected[k]) for k in expected)
    assert error<1e-6
    assert {r['trace_sha256'] for r in observed+examples}=={h.hexdigest()}
    assert len(example_checks)==5
    output=dict(schema='moonkvsim.historical_motivation_raw_reconstruction.v1',status='PASS',
                trace_sha256=h.hexdigest(),trace_path=str(a.trace.resolve()),sessions=sessions,
                qualifying_workflows=len(actual),max_csv_error_s=error,example_checks=example_checks,
                generator_sha256=sha(Path(__file__)),latency_prediction_reexecuted=False,
                latency_model_calibrated_to_trace_hardware=False,
                boundary='Observed timestamps, workflow gaps, nested hash-block input counts and harm arithmetic were independently reconstructed. Frozen AIConfigurator recomputation predictions were not rerun or physically validated.')
    (dat/'RAW_RECONSTRUCTION.json').write_text(json.dumps(output,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:output[k] for k in ('status','sessions','qualifying_workflows','max_csv_error_s','trace_sha256')}))

if __name__=='__main__':main()
