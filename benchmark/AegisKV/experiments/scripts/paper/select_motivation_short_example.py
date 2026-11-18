"""Reconstruct a shorter five-branch example from the pinned CC/Weka trace.

Selection is explicit: among strictly overlapping five-branch fan-outs, take
the smallest maximum branch duration (workflow ID and segment break ties).
For the selected fan-out, choose the all-LLM-active interval whose midpoint
is closest to the midpoint of the common branch overlap. Use its midpoint,
rounded to 0.1 s if that remains strictly inside the interval. This is a
selected illustration, not a sample for estimating population fault impact.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / "benchmark/AegisKV/experiments/data/motivation-short-cc"
PINNED_SHA = "29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276"
GAP_CSV = ROOT / "benchmark/AegisKV/experiments/data/motivation-real-cc/real-cc-workflow-parallel-gap.csv"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def groups(requests):
    i, segment = 0, 0
    while i < len(requests):
        if requests[i]["type"] != "subagent":
            i += 1
            continue
        segment += 1
        start = i
        while i < len(requests) and requests[i]["type"] == "subagent":
            i += 1
        yield segment, start, requests[start:i]


def select(trace):
    digest = hashlib.sha256()
    candidates, gaps = [], {}
    selected, selected_key = None, None
    sessions = 0
    with trace.open("rb") as stream:
        for line_no, raw in enumerate(stream, 1):
            digest.update(raw)
            if not raw.strip():
                continue
            workflow = json.loads(raw)
            sessions += 1
            for segment, top_index, group in groups(workflow["requests"]):
                starts = [float(b["t"]) for b in group]
                durations = [float(b["duration_ms"])/1000 for b in group]
                ends = [s+d for s, d in zip(starts, durations)]
                if len(group) < 2 or min(durations) <= 0 or max(starts) >= min(ends):
                    continue
                gap = max(durations)-min(durations)
                wid = str(workflow["id"])
                gaps[wid] = max(gaps.get(wid, 0), gap)
                if len(group) != 5:
                    continue
                row = dict(workflow_id=wid, fanout_segment_index=segment,
                           min_duration_s=min(durations), max_duration_s=max(durations),
                           overlap_start_s=max(starts), overlap_end_s=min(ends),
                           fanout_completion_s=max(ends))
                candidates.append(row)
                key = (max(durations), wid, segment)
                if selected_key is None or key < selected_key:
                    selected_key = key
                    selected = (workflow, group, row, line_no, top_index,
                                hashlib.sha256(raw).hexdigest())
    assert digest.hexdigest() == PINNED_SHA, "Source trace differs from the pinned Figure 1(a) source"
    with GAP_CSV.open() as stream:
        expected = {r["workflow_id"]: float(r["max_duration_gap_s"]) for r in csv.DictReader(stream)}
    assert set(expected) == set(gaps)
    gap_error = max(abs(gaps[k]-v) for k, v in expected.items())
    assert gap_error < 1e-6
    workflow, group, info, line_no, top_index, raw_line_sha = selected
    lo, hi = info["overlap_start_s"], info["overlap_end_s"]
    points = {lo, hi}
    for branch in group:
        for req in branch["requests"]:
            start, end = float(req["t"]), float(req["t"])+float(req.get("api_time", 0))
            if end > lo and start < hi:
                points.update((max(start, lo), min(end, hi)))
    points = sorted(points)
    intervals = []
    for left, right in zip(points, points[1:]):
        mid = (left+right)/2
        if all(any(float(r["t"]) < mid < float(r["t"])+float(r.get("api_time", 0))
                   for r in b["requests"]) for b in group):
            if intervals and abs(intervals[-1][1]-left) < 1e-9:
                intervals[-1] = (intervals[-1][0], right)
            else:
                intervals.append((left, right))
    assert intervals, "Shortest fan-out has no common active-LLM interval"
    left, right = min(intervals, key=lambda v: (abs(sum(v)/2-(lo+hi)/2), v[0]))
    mid = (left+right)/2
    failure = round(mid, 1)
    if not left < failure < right:
        failure = mid
    rows, branches = [], []
    for index, branch in enumerate(group):
        requests = branch["requests"]
        eligible = [(i, r) for i, r in enumerate(requests)
                    if float(r["t"]) <= failure and int(r.get("in", 0)) > 0]
        inner_index, prefix = max(eligible, key=lambda item: float(item[1]["t"]))
        assert float(prefix["t"]) < failure < float(prefix["t"])+float(prefix["api_time"])
        assert 8192 <= int(prefix["in"]) <= 131072, "Do not extrapolate the measured cost curve"
        assert int(prefix["in"]) == len(prefix["hash_ids"])*int(workflow["block_size"])
        start = float(branch["t"])
        duration = float(branch["duration_ms"])/1000
        end = start+duration
        rows.append(dict(
            trace_sha256=PINNED_SHA, workflow_id=info["workflow_id"],
            fanout_id=f"{info['workflow_id']}-fanout-{info['fanout_segment_index']}",
            fanout_segment_index=info["fanout_segment_index"], fanout_width=5,
            branch_index=index, agent_id=branch["agent_id"],
            branch_start_s=round(start, 6), branch_end_s=round(end, 6),
            duration_s=round(duration, 6), slack_s=round(info["fanout_completion_s"]-end, 6),
            overlap_start_s=round(lo, 6), overlap_end_s=round(hi, 6),
            fanout_completion_s=round(info["fanout_completion_s"], 6),
            failure_time_s=failure, prefix_request_start_s=float(prefix["t"]),
            prefix_request_api_time_s=float(prefix["api_time"]), prefix_tokens=int(prefix["in"]),
            parallel_definition="max_start_lt_min_end"))
        branches.append(dict(top_level_index=top_index+index,
                             branch={k: v for k, v in branch.items() if k != "requests"},
                             prefix_request_index=inner_index, prefix_request=prefix))
    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT / "short-example-failure-position.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    excerpt = OUT / "selected-trace-excerpt.json"
    top = workflow["requests"]
    excerpt.write_text(json.dumps(dict(
        workflow_id=info["workflow_id"], source_line=line_no, source_line_sha256=raw_line_sha,
        block_size=workflow["block_size"], hash_id_scope=workflow["hash_id_scope"],
        fanout_segment_index=info["fanout_segment_index"],
        preceding_main={k: v for k, v in top[top_index-1].items() if k != "hash_ids"} if top_index else None,
        following_main={k: v for k, v in top[top_index+len(group)].items() if k != "hash_ids"}
        if top_index+len(group) < len(top) else None,
        branches=branches), indent=2)+"\n")
    candidates.sort(key=lambda r: (r["max_duration_s"], r["workflow_id"], r["fanout_segment_index"]))
    record = dict(
        generator=str(Path(__file__).relative_to(ROOT)), generator_sha256=sha(Path(__file__)),
        source_path=str(trace.resolve()), source_sha256=PINNED_SHA,
        source_sessions=sessions, qualifying_gap_workflows=len(gaps), max_gap_csv_error_s=gap_error,
        selection_rule=__doc__.strip(), selected_workflow_id=info["workflow_id"],
        selected_fanout_segment_index=info["fanout_segment_index"],
        five_branch_candidates=candidates, failure_time_s=failure,
        all_active_intervals_s=intervals, selected_active_interval_s=[left, right],
        selected_duration_range_s=[min(r["duration_s"] for r in rows), max(r["duration_s"] for r in rows)],
        selected_prefix_range_tokens=[min(r["prefix_tokens"] for r in rows), max(r["prefix_tokens"] for r in rows)],
        files={str(p.relative_to(ROOT)): sha(p) for p in (csv_path, excerpt)},
        evidence_boundary="Selected short-fan-out illustration. Original timestamps and prefix hashes retained; "
        "no time rescaling. Recompute costs are substituted from the measured MiniCPM4 curve by the figure renderer; "
        "not a physical failure replay or a population effect estimate.")
    (OUT / "SELECTION.json").write_text(json.dumps(record, indent=2)+"\n")
    print(json.dumps({k: record[k] for k in ("selected_workflow_id", "failure_time_s", "selected_duration_range_s", "selected_prefix_range_tokens")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True, type=Path)
    select(parser.parse_args().trace)
