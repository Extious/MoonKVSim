#!/usr/bin/env python3
"""Recompute the archived SGLSim prefix characterization; no serving experiment."""

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "experiments/data/agent-prefix-reuse"
DEFAULT_TRACE = Path("/home/comp/zhanzhao/sglsim/AegisKV/doc/Archived/2026-08-06-pre-kvcache-centric/presentations/presentation/experiments/sglsim_large/traces/cc-traces-weka-062126/traces.materialized.jsonl")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    args = parser.parse_args()
    source = DATA / "original-analysis.py"
    spec = importlib.util.spec_from_file_location("archived_reuse_analysis", source)
    old = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old
    spec.loader.exec_module(old)
    aggregates = defaultdict(old.ReuseAggregate)
    compatible = defaultdict(old.ReuseAggregate)
    agents, sizes, scopes = set(), set(), set()
    models = Counter()
    workflows = 0
    mixed_model_workflows = 0
    proxy_mismatches = 0
    digest = hashlib.sha256()
    with args.trace.open("rb") as handle:
        for line in handle:
            digest.update(line)
            if not line.strip():
                continue
            trace = json.loads(line)
            workflows += 1
            block_size = int(trace.get("block_size", 64))
            sizes.add(block_size)
            scopes.add(str(trace.get("hash_id_scope")))
            requests, _ = old._flatten_requests(trace)
            raw_requests = []
            for item in trace["requests"]:
                raw_requests.extend(item.get("requests", []) if item.get("type") == "subagent" else [item])
            assert len(raw_requests) == len(requests)
            for request, raw in zip(requests, raw_requests):
                request.model = str(raw.get("model", ""))
            for key, result in old._analyze_reuse(requests, block_size).items():
                for field in result.__dataclass_fields__:
                    setattr(aggregates[key], field,
                            getattr(aggregates[key], field) + getattr(result, field))
            by_start = sorted(requests, key=lambda r: (r.start_s, r.serial))
            by_ready = sorted(requests, key=lambda r: (r.ready_s, r.serial))
            frontiers = {}
            seen = Counter()
            ready = 0
            for request in by_start:
                while ready < len(by_ready) and by_ready[ready].ready_s < request.start_s:
                    source_request = by_ready[ready]
                    frontiers.setdefault((source_request.agent_id, source_request.model), old.PrefixFrontier()).insert(
                        old.np.asarray(source_request.hash_ids, dtype=old.np.int32))
                    ready += 1
                sequence = old.np.asarray(request.hash_ids, dtype=old.np.int32)
                same_frontier = frontiers.get((request.agent_id, request.model))
                same = same_frontier.query(sequence) if same_frontier else 0
                cross = max((frontier.query(sequence) for (agent, model), frontier in frontiers.items()
                             if agent != request.agent_id and model == request.model), default=0)
                group = request.role + ("_first" if seen[request.agent_id] == 0 else "_later")
                for key in ["all", group]:
                    compatible[key].add(input_tokens=request.input_tokens,
                                        same_tokens=min(request.input_tokens, same * block_size),
                                        cross_tokens=min(request.input_tokens, cross * block_size))
                seen[request.agent_id] += 1
            agents.update((trace["id"], request.agent_id) for request in requests)
            proxy_mismatches += sum(r.input_tokens != len(r.hash_ids) * block_size for r in requests)
            workflow_models = set()
            for item in trace["requests"]:
                children = item.get("requests", []) if item.get("type") == "subagent" else [item]
                for request in children:
                    model = str(request.get("model", ""))
                    models[model] += 1
                    workflow_models.add(model)
            mixed_model_workflows += len(workflow_models) > 1
            if workflows % 50 == 0:
                print(f"Verified {workflows} workflows", flush=True)
    assert len(sizes) == 1, sizes
    rows = old._reuse_rows(aggregates, workflows=workflows, agents=len(agents), block_size=next(iter(sizes)))
    expected = list(csv.DictReader((DATA / "reuse-scope.csv").open()))
    assert rows == expected, "Recomputed values differ from the archived CSV"
    old._write_csv(DATA / "recomputed-reuse-scope.csv", rows)
    compatible_rows = old._reuse_rows(compatible, workflows=workflows, agents=len(agents), block_size=next(iter(sizes)))
    for original, filtered in zip(rows, compatible_rows):
        assert original["request_class"] == filtered["request_class"]
        for field in ["requests", "input_tokens"]:
            assert original[field] == filtered[field]
        for field in ["same_agent_tokens", "raw_cross_overlap_tokens"]:
            assert int(filtered[field]) <= int(original[field])
    for row in compatible_rows:
        row["evidence_tier"] = "real-trace-derived-completed-source-same-model-prefix"
        row["note"] += " Source and target must have identical recorded model names; no cross-workflow matching."
    old._write_csv(DATA / "same-model-reuse-scope.csv", compatible_rows)
    report = {
        "evidence": "observational trace characterization, not measured cache hits",
        "trace": str(args.trace.resolve()),
        "trace_sha256": digest.hexdigest(),
        "original_analysis_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "archived_csv_sha256": hashlib.sha256((DATA / "reuse-scope.csv").read_bytes()).hexdigest(),
        "exact_match_to_archived_csv": True,
        "workflows": workflows,
        "agents": len(agents),
        "requests": aggregates["all"].requests,
        "block_sizes": sorted(sizes),
        "hash_id_scopes": sorted(scopes),
        "input_proxy_count_mismatches": proxy_mismatches,
        "request_models": dict(models),
        "mixed_model_workflows": mixed_model_workflows,
        "plotted_csv": "same-model-reuse-scope.csv",
        "model_filter": "source.model == target.model, applied to both same-agent and other-agent sources",
        "scope": "within each workflow; ordered hash-prefix comparison; only sources completed strictly before target start",
        "denominator": "sum of input 64-token hash-block proxies over target requests in each group",
        "same_agent": "longest prefix available from any eligible source with same workflow-local agent ID",
        "other_agents": "longest prefix available from any eligible source with a different agent ID in the same workflow",
        "additional_other_agents": "max(0, other-agent prefix minus same-agent prefix), per request before summation",
        "limitations": [
            "Historical CSV does not filter models; new plotted CSV requires identical recorded model names. Weights/layout/residency are not observed.",
            "No cross-workflow comparison: hash IDs are trace-local.",
            "Source input-prefix blocks only; generated-output KV is not inserted independently.",
            "No capacity, eviction, routing, residency, failure, or WCT experiment.",
            "Token proxies are not exact tokenizer counts; see copied dataset README.",
            "Token-weighted aggregate, not mean per-request or per-agent coverage; no independent-run confidence interval."
        ],
    }
    (DATA / "audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
