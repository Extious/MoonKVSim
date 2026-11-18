#!/usr/bin/env python3
"""Publish only complete optimized runs with independently checked native refs."""
import argparse
import json
from pathlib import Path
from validate_prefill_one import validate


def validate_optimized(root):
    summary = validate(root)
    metadata = json.loads((root / "metadata.json").read_text())
    assert metadata["optimized_short_query_splits"] == 1
    assert metadata["optimized_long_query_splits"] == 1
    assert metadata["optimized_pack_gqa"] is False
    assert metadata["installed_framework_modified"] is False
    rows = [json.loads(s) for s in (root / "optimization-validation.jsonl").read_text().splitlines()]
    expected = {(c,"native_vs_optimized_one_token_same_prefix") for c in metadata["contexts"]}
    expected.update((c,"native_vs_optimized_full_prefill") for c in metadata["contexts"] if c <= 65536)
    assert {(r["context_tokens"],r["check"]) for r in rows} == expected
    assert len(rows) == len(expected) and all(r["correctness"] for r in rows)
    assert all(r["next_token_equal"] for r in rows if r["check"].endswith("same_prefix"))
    shape_set = {(8192,1),(8192,64),(65536,8192),(253953,1),(253970,64),(507905,1),(508000,128),(1010000,1)}
    for rank in range(metadata["tp"]):
        checks = [json.loads(s) for s in (root / f"operator-check-rank{rank}.jsonl").read_text().splitlines()]
        assert len(checks) == len(shape_set)
        assert {(r["context"],r["query_tokens"]) for r in checks} == shape_set
        assert all(r["correctness"] and r["rank"] == rank for r in checks)
    return {**summary,"native_reference_checks":rows,"operator_boundary_checks_per_rank":len(shape_set),
            "optimization":metadata["optimization"]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run",type=Path)
    args = ap.parse_args()
    print(json.dumps(validate_optimized(args.run),indent=2))
