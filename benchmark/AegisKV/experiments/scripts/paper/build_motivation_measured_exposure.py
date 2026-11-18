#!/usr/bin/env python3
"""Join verified physical Prefill timings to the frozen four-branch example.

Only reconstruction costs are measured. WCT increments are conditional
counterfactuals obtained by inserting those costs into the trace schedule.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[5]
DATA = ROOT / "benchmark/AegisKV/experiments/data"
PHYSICAL = DATA / "reuse-physical-qwen25-1m"
TRACE = DATA / "motivation-compact-cc/compact-example-failure-position.csv"
REFERENCE = PHYSICAL / "blsc/results/1517208/measured.json"
OUTPUT = TRACE.with_name("recovery-costs-measured.json")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def verify_raw(path):
    data = json.loads(path.read_text())
    assert data["evidence"] == "physical_worker_microbenchmark"
    covered = sorted({r["context_tokens"] for r in data["rows"]})
    audit = dict(job_id=data["metadata"]["job_id"], run_complete=data["run_complete"],
                 completed_contexts=covered, omitted_contexts=data["omitted_contexts"],
                 snapshot_prefixes={})
    if data["run_complete"]:
        assert not data["omitted_contexts"] and (path.parent / "COMPLETE").is_file()
    else:
        # The first job received its requested early TERM during the last point.
        # Only already sealed contexts are eligible; preserve the failed run.
        assert data["metadata"]["job_id"] == "1517915"
        assert covered == [100865, 105921, 108865] and data["omitted_contexts"] == [113665]
        assert (path.parent / "terminated-at.txt").is_file()
        assert all((path.parent / f"context-{c}-COMPLETE.json").is_file() for c in covered)
    for name, digest in data["source_sha256"].items():
        if sha(path.parent / name) != digest:
            # An append after the third sealed context does not invalidate its
            # hash-bound snapshot. Verify the exact prefix; never rewrite raw logs.
            assert not data["run_complete"] and name == "prefill-repeats-validation.jsonl", name
            raw = (path.parent / name).read_bytes()
            lines = raw.splitlines(keepends=True)
            selected = [line for line in lines if json.loads(line)["context_tokens"] in covered]
            prefix = b"".join(selected)
            assert raw.startswith(prefix) and hashlib.sha256(prefix).hexdigest() == digest
            assert all(json.loads(line)["context_tokens"] in data["omitted_contexts"]
                       for line in lines[len(selected):])
            audit["snapshot_prefixes"][name] = dict(bytes=len(prefix), sha256=digest,
                                                      complete_file_sha256=sha(path.parent / name))
    assert all(r["correctness"] and r["status"] == "ok"
               for r in jsonl(path.parent / "trials.jsonl"))
    return data, audit


def build(measured_paths):
    reference, _ = verify_raw(REFERENCE)
    original = reference["metadata"]
    keys = ("model", "revision", "framework", "torch", "cuda", "gpu", "tp", "dtype", "batch",
            "new_tokens", "chunk_tokens", "attention", "forward_mode", "endpoint", "history_tokens",
            "inputs", "input_kind", "timing", "framework_source_sha256", "adapter_sha256",
            "framework_package_version", "activation_backend", "kernel_build", "sparse_kernel_build",
            "sparse_config_sha256", "sparse_head_group", "sparse_min_queries", "sparse_context_threshold",
            "sparse_gqa_schedule", "sparse_selector_release", "short_query_attention", "sparse_adapter_sha256")
    old_archive = PHYSICAL / "sparse-archive" / original["job_id"]
    # Timing repetition changed; the actual model, attention and input paths did not.
    same_code = ("sg_sparse_backend.py", "sg_backend.py", "dca_grouped.py", "measure.py",
                 "layerwise_restore.py", "measure_prefill_optimized.py",
                 "sparse-config/Qwen2.5_7B_Instruct_1M.json", "sparse-config/manifest.json")
    with TRACE.open() as f:
        trace = list(csv.DictReader(f))
    assert len(trace) == 4 and len({r["workflow_id"] for r in trace}) == 1
    contexts = sorted(int(r["prefix_tokens"]) + 1 for r in trace)
    full, trials, audit, sources = {}, [], [], [TRACE, TRACE.with_name("SELECTION.json"), REFERENCE, Path(__file__)]
    source_jobs = {}
    for measured in measured_paths:
        physical, proof = verify_raw(measured)
        meta = physical["metadata"]
        assert all(meta[k] == original[k] for k in keys), {
            k: (meta.get(k), original.get(k)) for k in keys if meta.get(k) != original.get(k)}
        assert meta["repeats_by_path"]["FullPrefill"] == 3
        assert meta["full_prefill_warmup_limit"] == "one full-length warmup at every measured context"
        archive = PHYSICAL / "sparse-archive" / meta["job_id"]
        archived = json.loads((archive / "source-sha256.json").read_text())
        for name, digest in archived.items():
            assert sha(archive / name) == digest, name
        assert all(sha(archive / n) == sha(old_archive / n) for n in same_code)
        assert sha(archive / "measure_prefill_sparse.py") == meta["script_sha256"]
        completed = proof["completed_contexts"]
        assert set(completed) <= set(contexts)
        for r in physical["rows"]:
            if r["path"] == "FullPrefill":
                c = r["context_tokens"]
                assert c not in full, "Do not choose among competing samples"
                full[c], source_jobs[c] = r, meta["job_id"]
        trials += [t for t in jsonl(measured.parent / "trials.jsonl") if t["context_tokens"] in completed]
        validation = [v for v in jsonl(measured.parent / "prefill-repeats-validation.jsonl")
                      if v["context_tokens"] in completed]
        assert len(validation) == 3 * len(completed) and all(v["correctness"] for v in validation)
        audit.append(proof)
        sources += [measured, archive / "source-sha256.json"]
        sources += [measured.parent / n for n in physical["source_sha256"]]
        sources += [measured.parent / f"context-{c}-COMPLETE.json" for c in completed]
    assert sorted(full) == contexts
    cases = []
    for branch in trace:
        history = int(branch["prefix_tokens"])
        context = history + 1
        rows = [t for t in trials if t["path"] == "FullPrefill" and t["context_tokens"] == context]
        warmups = [r for r in rows if r["warmup"]]
        timings = [r for r in rows if not r["warmup"]]
        assert len(warmups) == 1 and len(timings) == 3
        assert sorted(r["repetition"] for r in timings) == [0, 1, 2]
        assert all(r["history_tokens"] == history and r["new_tokens"] == 1 for r in rows)
        assert len({r["input_sha256"] for r in rows}) == 1
        values = [r["latency_ms"] / 1000 for r in timings]
        value = statistics.median(values)
        summary = full[context]
        assert summary["status"] == "measured" and summary["timing_repeats_per_input"] == 3
        assert abs(value - summary["latency_ms"] / 1000) < 1e-10
        assert min(values) == summary["trial_min_ms"] / 1000
        assert max(values) == summary["trial_max_ms"] / 1000
        slack = float(branch["slack_s"])
        branch_end = float(branch["branch_end_s"])
        join = float(branch["fanout_completion_s"])
        assert abs(slack - (join - branch_end)) < 1e-8
        loss = max(value - slack, 0)
        # Independently recompute the delayed join, retaining the other branches.
        changed_join = max(branch_end + value, *(float(r["branch_end_s"]) for r in trace
                                                if r["branch_index"] != branch["branch_index"]))
        assert abs(loss - (changed_join - join)) < 1e-8
        cases.append(dict(branch_index=int(branch["branch_index"]),
                          branch=f"A{int(branch['branch_index'])+1}", prefix_tokens=history,
                          source_job_id=source_jobs[context],
                          context_tokens=context, new_tokens=1, recompute_s=value,
                          trial_min_s=min(values), trial_max_s=max(values), trials_s=values,
                          input_sha256=timings[0]["input_sha256"], slack_s=slack,
                          absorbed_s=min(value, slack), wct_increase_s=loss))
    result = dict(evidence="measured_prefill_costs+trace_conditional_counterfactual",
                  cost_evidence="physical_worker_microbenchmark", wct_evidence="calculated_not_fault_injected",
                  model=original["model"], job_ids=[a["job_id"] for a in audit],
                  configuration={k: original[k] for k in keys},
                  same_configuration_reference=str(REFERENCE.relative_to(ROOT)),
                  matched_source_files=list(same_code), source_sha256={str(p.relative_to(ROOT)): sha(p) for p in sources},
                  physical_source_audit=audit, workflow_id=trace[0]["workflow_id"],
                  failure_after_fork_s=float(trace[0]["failure_time_s"]) - min(float(r["branch_start_s"]) for r in trace),
                  prefix_definition="trace input hash-block count times 64; length proxy, not original tokenizer length",
                  experimental_unit="two physical allocations: three complete lengths plus the resumed last length; one synthetic input; three timings per length after one warmup",
                  incomplete_samples="The interrupted last context's partial timings remain in raw job 1517915 but are excluded as a whole; only its independently completed resumption is plotted.",
                  counterfactual="insert measured full-Prefill duration as added pause on one branch; assumed all-branch join; other timing and queues fixed",
                  scope="Qwen reconstruction cost applied to Claude trace positions; not replay of original prompts or observed failure WCT",
                  workflow_costs=cases)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measured", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    result = build([p.resolve() for p in args.measured])
    print(json.dumps({"output": str(OUTPUT), "cases": result["workflow_costs"]}, indent=2))
