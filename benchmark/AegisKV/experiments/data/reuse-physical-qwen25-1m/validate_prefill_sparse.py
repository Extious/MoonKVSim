"""Reject incomplete matrices, mismatched restores, and invalid stream ordering."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics

from layerwise_restore import intersection_ms


def lines(path):
    return [json.loads(s) for s in path.read_text().splitlines() if s.strip()]


def validate(root):
    root = Path(root)
    assert (root/"COMPLETE").is_file()
    assert not list(root.glob("failure-rank*.json"))
    data = json.loads((root/"measured.json").read_text())
    meta = data["metadata"]
    assert data["run_complete"] and not data["omitted_contexts"]
    assert data["evidence"] == "physical_worker_microbenchmark"
    assert meta["protocol"] in ("sparse_prefill_kv_fill_one_token_v1", "sparse_prefill_kv_fill_one_token_v2",
                                "sparse_prefill_kv_fill_one_token_v3_sharedfs")
    assert meta == json.loads((root/"metadata.json").read_text())
    assert meta["tp"] == 2 and meta["new_tokens"] == 1 and meta["dtype"] == "BF16"
    assert meta["sparse_min_queries"] == 1 and meta["sparse_context_threshold"] == 32768
    assert meta["sparse_runtime_enabled"] is True
    for name, digest in data["source_sha256"].items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest() == digest, name
    contexts = meta["contexts"]
    paths = {"FullPrefill", "HBM", "DRAM_no_overlap"}
    if meta["protocol"].endswith("v1"):
        paths.add("DRAM_overlap")
    if meta["protocol"].endswith("v3_sharedfs"):
        paths.add("SharedFS_no_overlap")
        preflight = json.loads((root/"sharedfs-compute-preflight.json").read_text())
        assert preflight == meta["sharedfs_preflight"] and preflight["correctness"]
        assert preflight["read"]["direct_io"] and preflight["write"]["direct_io"]
        assert preflight["client_cache_before"]["resident_pages"] == 0
        assert preflight["client_cache_after"]["resident_pages"] == 0
    repetitions = {p: ([0] if p in ("FullPrefill", "SharedFS_no_overlap") else [-1,0,1,2]) for p in paths}
    assert set(meta["paths"]) == paths
    trials = lines(root/"trials.jsonl")
    assert all(r["correctness"] and r["status"] == "ok" for r in trials)
    assert len(trials) == len(contexts)*sum(map(len, repetitions.values()))
    summaries = {(r["context_tokens"], r["path"]):r for r in data["rows"]}
    assert len(summaries) == len(data["rows"]) == len(contexts)*len(paths)
    for context in contexts:
        assert (root/f"context-{context}-COMPLETE.json").is_file()
        hashes = {r["input_sha256"] for r in trials if r["context_tokens"] == context}
        assert len(hashes) == 1
        for path in paths:
            group = [r for r in trials if r["context_tokens"] == context and r["path"] == path]
            assert all(r["new_tokens"] == 1 and r["history_tokens"] == context-1 for r in group)
            assert sorted(r["repetition"] for r in group) == repetitions[path]
            expected_bytes = (context-1)*28*2*4*128*2 if path not in ("HBM", "FullPrefill") else 0
            assert all(r["transferred_bytes"] == expected_bytes for r in group)
            if path == "FullPrefill":
                assert (group[0]["sparse_prefix_layer_calls"] > 0) == (context > 32768)
                assert (group[0]["sparse_prefix_kernel_calls"] > 0) == (context > 32768)
            else:
                assert all(r["greedy_equal"] for r in group)
                assert all((r["new_token_sparse_kernel_calls"] > 0) == (context > 32768) for r in group)
                assert next(r for r in group if r["repetition"] == 0)["history_bitwise_equal"]
            if path == "SharedFS_no_overlap":
                expected_disk_bytes = (((context-1)*512+65535)//65536)*65536*56*2
                assert group[0]["storage_read_bytes"] == expected_disk_bytes
                assert group[0]["storage_file_sha256_equal"]
                assert group[0]["client_cache_resident_pages_before"] == 0
                assert group[0]["client_cache_resident_pages_after"] == 0
            values = [r["latency_ms"] for r in group if not r["warmup"]]
            row = summaries[context,path]
            assert all(x > 0 for x in values)
            assert row["latency_ms"] == statistics.median(values)
            assert row["trial_min_ms"] == min(values) and row["trial_max_ms"] == max(values)
            assert row["timing_repeats_per_input"] == len(values)
    validation = lines(root/"validation.jsonl")
    assert len(validation) == len(contexts) and all(r["correctness"] for r in validation)
    model_checks = lines(root/"sparse-model-validation.jsonl") if 65536 in contexts else []
    assert len(model_checks) == int(65536 in contexts) and all(r["correctness"] for r in model_checks)
    overlap = []
    for rank in range(2):
        checks = lines(root/f"sparse-operator-rank{rank}.jsonl")
        expected = {(65536, 1), (65536, 128), (253968, 128), (300000, 128)}
        if "sparse_gqa_schedule" in meta:
            expected |= {(300000, 1), (600000, 1)}
        if meta.get("sparse_selector_release"):
            expected.add((1010000, 8192))
        assert {(r["context_tokens"], r["queries"]) for r in checks} == expected
        assert len(checks) == len(expected) and all(r["correctness"] and r["finite"] for r in checks)
        if "SharedFS_no_overlap" in paths:
            storage = lines(root/f"storage-rank{rank}.jsonl")
            assert len(storage) == 2*len(contexts)
            for c in contexts:
                writes = [r for r in storage if r["context_tokens"] == c and r["event"] == "checkpoint_written"]
                reads = [r for r in storage if r["context_tokens"] == c and r["event"] == "checkpoint_read"]
                assert len(writes) == len(reads) == 1
                w, r = writes[0], reads[0]
                assert w["sha256"] == r["sha256"] and r["sha256_equal"]
                expected_logical = (c-1)*28*2*2*128*2
                expected_disk = (((c-1)*512+65535)//65536)*65536*56
                assert w["logical_bytes"] == r["logical_bytes"] == expected_logical
                assert w["bytes"] == r["bytes"] == expected_disk
                assert w["direct_io"] and r["direct_io"]
                assert w["rank"] == r["rank"] == rank
                assert r["client_cache_before"]["resident_pages"] == r["client_cache_after"]["resident_pages"] == 0
        timeline = lines(root/f"timeline-rank{rank}.jsonl")
        expected = {(c,p,r) for c in contexts for p in paths-{"FullPrefill"} for r in repetitions[p]}
        assert {(r["context_tokens"],r["path"],r["repetition"]) for r in timeline} == expected
        assert len(timeline) == len(expected)
        for row in timeline:
            assert row["rank"] == rank and row["visited_layers"] == list(range(28))
            assert row["layer_dependencies_satisfied"]
            cp, comp = row["copy_intervals_ms"], row["compute_intervals_ms"]
            assert len(comp) == 28 and len(cp) == (0 if row["path"] == "HBM" else 28)
            for series in (cp,comp):
                assert all(0 <= a <= b for a,b in series)
                assert all(series[i][1] <= series[i+1][0]+.05 for i in range(len(series)-1))
            assert all(comp[i][0]+.05 >= cp[i][1] for i in range(len(cp)))
            shared = intersection_ms(cp,comp)
            assert abs(shared-row["concurrent_interval_ms"]) < 1e-5
            if row["path"] != "DRAM_overlap":
                assert shared < .05
            elif row["repetition"] >= 0:
                overlap.append(dict(context_tokens=row["context_tokens"],rank=rank,
                                    repetition=row["repetition"], concurrent_ms=shared,
                                    copy_ms=row["sum_copy_interval_ms"]))
        if max(contexts) >= 65536 and "DRAM_overlap" in paths:
            assert any(r["rank"] == rank and r["concurrent_ms"] > 0 for r in overlap), "No physical overlap observed"
    report = {"passed": True, "contexts": contexts, "formal_timings": sum(not r["warmup"] for r in trials),
              "paths": sorted(paths), "serialized_dram_ordering_verified": True,
              "overlap_scope": ("CUDA copy intervals intersect layer-forward intervals; forward intervals can include CPU dispatch gaps, not a kernel-utilization trace"
                                if "DRAM_overlap" in paths else "not measured in this allocation"),
              "warmups": sum(r["warmup"] for r in trials), "model_checks": model_checks,
              "sharedfs_checked": "SharedFS_no_overlap" in paths,
              "overlap_timings": overlap, "source_sha256": data["source_sha256"]}
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    args = ap.parse_args()
    print(json.dumps(validate(args.run), indent=2))
