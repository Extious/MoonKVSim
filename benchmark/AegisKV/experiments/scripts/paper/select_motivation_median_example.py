"""Choose the workflow-maximum duration gap nearest Figure 1(a)'s median.

Rank the same equally weighted workflow maxima as the ECDF by absolute
distance to its median, breaking ties by workflow ID. Do not rank by
recovery cost, slack or loss. Partition the common branch overlap at all
LLM request boundaries. Among intervals with exactly one active request
per branch, choose the midpoint closest to the common-overlap midpoint;
round to 0.1 s only if still inside that interval. Require all prefixes
inside the measured cost domain; do not extrapolate or search for a more
favorable failure time. The median example is descriptive, not an estimate
of population failure impact.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

from select_motivation_short_example import PINNED_SHA, ROOT, groups

FANIN = ROOT / "benchmark/AegisKV/experiments/data/motivation-fanin-cc"
OUT = ROOT / "benchmark/AegisKV/experiments/data/motivation-median-cc"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select(trace):
    selection_path = FANIN / "SELECTION.json"
    population = json.loads(selection_path.read_text())
    for path, digest in population["files"].items():
        assert sha(ROOT/path) == digest
    gap_path, audit_path = FANIN/"workflow-parallel-gap.csv", FANIN/"group-audit.json"
    rows = list(csv.DictReader(gap_path.open()))
    median = float(np.median([float(r["max_duration_gap_s"]) for r in rows]))
    chosen = min(rows, key=lambda r: (abs(float(r["max_duration_gap_s"])-median), r["workflow_id"]))
    evidence = next(r for r in json.loads(audit_path.read_text())
                    if r["fanout_id"] == chosen["selected_fanout_id"])
    assert evidence["classification"] == "retained_temporal_fanin"
    digest, workflow = hashlib.sha256(), None
    with trace.open("rb") as stream:
        for line_no, raw in enumerate(stream, 1):
            digest.update(raw)
            if line_no == evidence["source_line"]:
                assert hashlib.sha256(raw).hexdigest() == evidence["source_line_sha256"]
                workflow = json.loads(raw)
    assert digest.hexdigest() == PINNED_SHA == population["source_sha256"]
    assert workflow["id"] == chosen["workflow_id"]
    segment, begin, group = next(x for x in groups(workflow["requests"])
                                if x[0] == evidence["fanout_segment_index"])
    starts = [float(b["t"]) for b in group]
    durations = [float(b["duration_ms"])/1000 for b in group]
    ends = [s+d for s, d in zip(starts, durations)]
    lo, hi, join = max(starts), min(ends), max(ends)
    assert lo < hi and all(b["status"] == "completed" for b in group)
    assert abs(max(durations)-min(durations)-float(chosen["max_duration_gap_s"])) < 1e-6
    following_main = workflow["requests"][evidence["following_main_index"]]
    assert following_main["type"] != "subagent" and float(following_main["t"]) >= join
    points = {lo, hi}
    for b in group:
        for r in b["requests"]:
            start, end = float(r["t"]), float(r["t"])+float(r.get("api_time", 0))
            if start < hi and end > lo:
                points.update((max(start, lo), min(end, hi)))
    points, intervals = sorted(points), []
    for left, right in zip(points, points[1:]):
        mid = (left+right)/2
        active = [[(i, r) for i, r in enumerate(b["requests"])
                   if float(r["t"]) < mid < float(r["t"])+float(r.get("api_time", 0))]
                  for b in group]
        if all(len(r) == 1 for r in active):
            intervals.append((left, right, active))
    assert intervals, "Median example has no common active-LLM interval"
    left, right, active = min(intervals, key=lambda x: (abs((x[0]+x[1])/2-(lo+hi)/2), x[0]))
    failure = round((left+right)/2, 1)
    if not left < failure < right:
        failure = (left+right)/2
    output, branches = [], []
    for i, (branch, request) in enumerate(zip(group, active)):
        ri, prefix = request[0]
        assert float(prefix["t"]) < failure < float(prefix["t"])+float(prefix["api_time"])
        assert 8192 <= int(prefix["in"]) <= 131072, "Do not extrapolate measured costs"
        assert int(prefix["in"]) == len(prefix["hash_ids"])*int(workflow["block_size"])
        output.append(dict(
            trace_sha256=PINNED_SHA, workflow_id=workflow["id"], fanout_id=evidence["fanout_id"],
            fanout_segment_index=segment, fanout_width=len(group), branch_index=i,
            agent_id=branch["agent_id"], branch_start_s=round(starts[i], 6),
            branch_end_s=round(ends[i], 6), duration_s=round(durations[i], 6),
            slack_s=round(join-ends[i], 6), overlap_start_s=lo, overlap_end_s=hi,
            fanout_completion_s=join, failure_time_s=failure,
            prefix_request_start_s=float(prefix["t"]), prefix_request_api_time_s=float(prefix["api_time"]),
            prefix_tokens=int(prefix["in"]), parallel_definition="max_start_lt_min_end"))
        branches.append(dict(top_level_index=begin+i,
                             branch={k:v for k,v in branch.items() if k != "requests"},
                             prefix_request_index=ri, prefix_request=prefix))
    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT/"median-example-failure-position.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    excerpt_path = OUT/"selected-trace-excerpt.json"
    excerpt_path.write_text(json.dumps(dict(
        workflow_id=workflow["id"], source_line=evidence["source_line"],
        source_line_sha256=evidence["source_line_sha256"], block_size=workflow["block_size"],
        hash_id_scope=workflow["hash_id_scope"], fanout_segment_index=segment,
        preceding_main={k:v for k,v in workflow["requests"][begin-1].items() if k != "hash_ids"} if begin else None,
        following_main={k:v for k,v in following_main.items() if k != "hash_ids"},
        following_main_index=evidence["following_main_index"], branches=branches), indent=2)+"\n")
    record = dict(
        generator=str(Path(__file__).relative_to(ROOT)), generator_sha256=sha(Path(__file__)),
        source_path=str(trace.resolve()), source_sha256=PINNED_SHA,
        selection_rule=__doc__.strip(), population_workflows=len(rows), target_median_s=median,
        selected_duration_gap_s=max(durations)-min(durations),
        median_distance_s=abs(max(durations)-min(durations)-median),
        selected_workflow_id=workflow["id"], selected_fanout_segment_index=segment,
        fanout_width=len(group), selected_duration_range_s=[min(durations),max(durations)],
        selected_prefix_range_tokens=[min(r["prefix_tokens"] for r in output),max(r["prefix_tokens"] for r in output)],
        failure_time_s=failure, display_time_origin_s=min(starts),
        failure_time_since_fork_s=failure-min(starts), join_time_since_fork_s=join-min(starts),
        following_main_start_s=float(following_main["t"]),
        all_active_intervals_s=[[x[0],x[1]] for x in intervals], selected_active_interval_s=[left,right],
        source_sha256_by_path={str(p.relative_to(ROOT)):sha(p) for p in
                              (selection_path,gap_path,audit_path,Path(__file__).with_name("select_motivation_short_example.py"))},
        files={str(p.relative_to(ROOT)):sha(p) for p in (csv_path,excerpt_path)},
        evidence_boundary="Exact median of workflow-maximum duration gaps, not representative "
        "population failure impact. Fan-in is inferred from timing. Figure 1(b) subtracts "
        "the earliest branch start for readable ticks without rescaling time. Figure 1(c) "
        "substitutes measured MiniCPM4 full-prefill costs; not original-model failure replay.")
    (OUT/"SELECTION.json").write_text(json.dumps(record,indent=2)+"\n")
    print(json.dumps({k:record[k] for k in ("selected_workflow_id","fanout_width","selected_duration_gap_s","target_median_s","failure_time_s","failure_time_since_fork_s","selected_prefix_range_tokens")},indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True, type=Path)
    select(parser.parse_args().trace)
