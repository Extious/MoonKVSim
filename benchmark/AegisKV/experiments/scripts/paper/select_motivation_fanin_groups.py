"""Select temporally inferred fan-ins; Main may execute during a fan-out.

For each contiguous subagent group with a common execution overlap, require
completed branches and a later Main request starting at/after every branch
finishes. Use the earliest such Main request. This is a temporal proxy, not
an observed result-consumption edge: the source trace contains no join IDs.
Filter groups first, then retain the maximum duration gap per workflow.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np

from select_motivation_short_example import GAP_CSV, PINNED_SHA, ROOT, groups

OUT = ROOT / "benchmark/AegisKV/experiments/data/motivation-fanin-cc"
REFERENCE_SHORT_EXAMPLE = "81fad784ca8c3f4136179dc73184409d21a2-fanout-1"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select(trace):
    digest = hashlib.sha256()
    audited, old_maxima, sessions = [], {}, 0
    with trace.open("rb") as stream:
        for line_no, raw in enumerate(stream, 1):
            digest.update(raw)
            if not raw.strip():
                continue
            workflow = json.loads(raw)
            sessions += 1
            top = workflow["requests"]
            main = [(i, r) for i, r in enumerate(top) if r["type"] != "subagent"]
            for segment, begin, group in groups(top):
                starts = [float(b["t"]) for b in group]
                durations = [float(b["duration_ms"])/1000 for b in group]
                ends = [s+d for s, d in zip(starts, durations)]
                if len(group) < 2 or min(durations) <= 0 or max(starts) >= min(ends):
                    continue
                wid = str(workflow["id"])
                gap = max(durations)-min(durations)
                old_maxima[wid] = max(old_maxima.get(wid, 0), gap)
                end_index = begin+len(group)
                successors = [(i, r) for i, r in main
                              if i >= end_index and float(r["t"]) >= max(ends)]
                successor = min(successors, key=lambda ir: (float(ir[1]["t"]), ir[0])) if successors else None
                reason = ("incomplete_branch" if any(b.get("status") != "completed" for b in group)
                          else "no_main_after_all_branches" if successor is None
                          else "retained_temporal_fanin")
                row = dict(
                    workflow_id=wid, fanout_id=f"{wid}-fanout-{segment}",
                    source_line=line_no, source_line_sha256=hashlib.sha256(raw).hexdigest(),
                    fanout_segment_index=segment, top_level_indices=list(range(begin, end_index)),
                    branch_statuses=[b.get("status") for b in group],
                    fanout_width=len(group), first_branch_start_s=min(starts),
                    last_branch_end_s=max(ends), overlap_start_s=max(starts),
                    overlap_end_s=min(ends), fastest_duration_s=min(durations),
                    slowest_duration_s=max(durations), duration_gap_s=gap,
                    main_requests_submitted_during_branches=sum(
                        min(starts) <= float(r["t"]) < max(ends) for _, r in main),
                    main_requests_executing_during_branches=sum(
                        float(r["t"]) < max(ends) and float(r["t"])+float(r.get("api_time", 0)) > min(starts)
                        for _, r in main),
                    following_main_index=successor[0] if successor else None,
                    following_main_start_s=float(successor[1]["t"]) if successor else None,
                    last_finish_to_main_s=float(successor[1]["t"])-max(ends) if successor else None,
                    classification=reason)
                audited.append(row)
    assert digest.hexdigest() == PINNED_SHA, "Pinned trace mismatch"
    original = {r["workflow_id"]: r for r in csv.DictReader(GAP_CSV.open())}
    assert set(original) == set(old_maxima)
    assert max(abs(old_maxima[k]-float(r["max_duration_gap_s"])) for k, r in original.items()) < 1e-6
    retained = [r for r in audited if r["classification"] == "retained_temporal_fanin"]
    counts = Counter(r["workflow_id"] for r in retained)
    selected = {}
    for row in retained:
        wid = row["workflow_id"]
        if wid not in selected or row["duration_gap_s"] > selected[wid]["duration_gap_s"]:
            selected[wid] = row
    rows = [dict(
        trace_sha256=PINNED_SHA, workflow_id=wid, selected_fanout_id=r["fanout_id"],
        qualifying_fanin_count=counts[wid], fanout_width=r["fanout_width"],
        overlap_start_s=r["overlap_start_s"], overlap_end_s=r["overlap_end_s"],
        fastest_duration_s=r["fastest_duration_s"], slowest_duration_s=r["slowest_duration_s"],
        max_duration_gap_s=r["duration_gap_s"], following_main_start_s=r["following_main_start_s"],
        main_requests_submitted_during_branches=r["main_requests_submitted_during_branches"],
        selection_rule="max_gap_per_workflow_after_temporal_fanin_filter",
        parallel_definition="max_start_lt_min_end", fanin_definition="completed_branches_then_later_main_main_overlap_allowed")
        for wid, r in sorted(selected.items())]
    gap = np.array([r["max_duration_gap_s"] for r in rows])
    example = next(r for r in audited if r["fanout_id"] == REFERENCE_SHORT_EXAMPLE)
    assert example["classification"] == "retained_temporal_fanin"
    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT / "workflow-parallel-gap.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    audit_path = OUT / "group-audit.json"
    audit_path.write_text(json.dumps(audited, indent=2)+"\n")
    record = dict(
        generator=str(Path(__file__).relative_to(ROOT)), generator_sha256=sha(Path(__file__)),
        source_path=str(trace.resolve()), source_sha256=PINNED_SHA, source_sessions=sessions,
        selection_rule=__doc__.strip(), evidence_boundary="Temporal inference only. A later Main request "
        "does not prove consumption of all branch outputs. Main activity during the fan-out is allowed. "
        "Duration gaps are not join slack or observed failure tolerance.",
        original_workflows=len(original), original_qualifying_groups=len(audited),
        group_classifications=dict(Counter(r["classification"] for r in audited)),
        retained_groups=len(retained), retained_workflows=len(rows),
        retained_groups_with_main_submissions=sum(r["main_requests_submitted_during_branches"] > 0 for r in retained),
        retained_groups_with_main_execution=sum(r["main_requests_executing_during_branches"] > 0 for r in retained),
        dropped_workflows=sorted(set(original)-set(selected)),
        changed_selected_fanouts=[wid for wid, r in selected.items()
                                 if r["fanout_id"] != original[wid]["selected_fanout_id"]],
        median_duration_gap_s=float(np.median(gap)), p90_duration_gap_s=float(np.percentile(gap, 90)),
        reference_short_example=example,
        files={str(p.relative_to(ROOT)): sha(p) for p in (csv_path, audit_path)})
    (OUT / "SELECTION.json").write_text(json.dumps(record, indent=2)+"\n")
    print(json.dumps({k:v for k,v in record.items() if k not in ("files", "selection_rule", "reference_short_example")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True, type=Path)
    select(parser.parse_args().trace)
