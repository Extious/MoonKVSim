#!/usr/bin/env python3
"""Prepare and run a frozen native-demand raw-KV transfer component experiment."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import platform
import shutil
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

import numpy as np

ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924"
ENGINE = ROOT / "python/moonkvsim/aegiskv/evaluation_native_transfer.py"
SPEC = importlib.util.spec_from_file_location("native_transfer_engine", ENGINE)
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def read(path):
    return json.loads(path.read_text())


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def protocol():
    return dict(
        schema="aegiskv.native-raw-kv-transfer-component.v1",
        declared_utc=datetime.now(UTC).isoformat(),
        models=["NOSA-8B", "NSA-8B", "MiniCPM4.1-8B"],
        documents=["10146", "10321", "10356"],
        M=[32000, 32256],
        primary_M=32000,
        future_queries=256,
        methods=["DRAM", "Current", "Recency", "Oracle"],
        bandwidth_GBps=[8, 16, 32],
        layer_compute_ns=[0, 25600, 256000, 2560000],
        scenarios=864,
        layers=32,
        kv_heads=2,
        head_dim=128,
        element_bytes=2,
        block_tokens=64,
        block_bytes=65536,
        K=16,
        L=4,
        checkpoint_tokens=256,
        beta=0.9,
        epsilon=0.1,
        counter="full causal q0..M history; union groups once per query; C=(C+new256)*.9",
        current_residency=(
            "first four layers: checkpoint lifecycle, strict 1.1 hysteresis, earlier-index ties"
        ),
        later_layer_ranking=(
            "same Current final counters, top16 without incumbent; identical for every method"
        ),
        recency_residency="last16 complete historical blocks of each first4 layers",
        oracle_residency=(
            "same budget, first4 layers future256 frequency top16; future-aware, "
            "not latency-optimal"
        ),
        background=(
            "same sequence for all variants: layer-ordered Current top16, then "
            "layer-ordered remaining checkpoint blocks; skip resident/completed"
        ),
        release="all256 native query demands of a layer reveal simultaneously at that layer entry",
        demand=(
            "physical raw-KV blocks unioned across2 KV groups; causal rebuilt tail "
            "is local, never transferred"
        ),
        transfer=(
            "one continuous H2D link; sorted-object urgent demand precedes "
            "background; zero-cost fluid preemption preserves serviced bytes"
        ),
        compute=(
            "declared per-layer constant sensitivity only; hit compute "
            "proportional to selected block-reference count overlaps H2D; miss "
            "compute follows KV-ready"
        ),
        query_ready=(
            "max(layer entry, completion of required historical raw-KV copies); no "
            "query kernel/output time claim"
        ),
        initial_conditions=(
            "complete raw-KV checkpoint in DRAM; firstL prepared blocks in target "
            "HBM; equally ready selector/auxiliary state assumed for every method "
            "including DRAM"
        ),
        memory=(
            "enough destination workspace for the complete raw-KV checkpoint; "
            "retain transferred blocks; no eviction"
        ),
        stop=(
            "after layer32 assumed computation; account partial copies and "
            "untransferred remainder; no requirement to restore unused checkpoint "
            "objects"
        ),
        preparation=(
            "initial residency and normal-time replacement traffic/cost excluded; "
            "resident bytes reported"
        ),
        statistics=(
            "three documents per model; per-document paired differences then "
            "equal-document mean/min/max; layers/queries/M/BW/compute are not "
            "independent samples; no CI"
        ),
        exclusions=[
            (
                "native selector calculation and compressed/index/window "
                "auxiliary-state readiness cost"
            ),
            "attention arithmetic, QK/softmax/LSE kernels, actual native compute timing",
            "detection, routing, readmission, queues, multi-request/TP/network contention",
            "full recovery completion, first generated token, Agent latency, WCT",
            "preparation cost and capacity competition",
        ],
        limitations=[
            (
                "native selections originate from full causal prefill; not proof of "
                "equivalent chunked/resume execution"
            ),
            "MiniCPM sparse dispatch threshold can differ on short separate forwards",
            "layer-entry release is assumed, not measured selector availability",
            (
                "zero compute isolates raw demanded-byte transfer boundary; nonzero "
                "values are uncalibrated sensitivities"
            ),
            (
                "frequency oracle maximizes event coverage, not guaranteed minimum "
                "time at nonzero compute"
            ),
            (
                "local tail availability is assumed after local projection; native "
                "auxiliary state is not simulated"
            ),
            "negative and zero differences remain in all outputs",
        ],
    )


def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / "PROTOCOL.json", protocol())  # Before inspecting any timing outcome.
    (out / "inputs").mkdir()
    manifest_path = BASE / "inputs/native-heldout-selector-manifest.json"
    manifest = read(manifest_path)
    warm_audit_path = BASE / "native-topk-warm/AUDIT.json"
    warm_counts_path = BASE / "native-topk-warm/whole-history-chunk-counts.npz"
    warm_audit = read(warm_audit_path)
    warm_expected = warm_audit.get("artifacts_sha256", {}).get(warm_counts_path.name)
    if warm_expected is None:
        # Different prior audit schemas must be inspected explicitly, not silently ignored.
        candidates = []

        def scan(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key.endswith(warm_counts_path.name) and isinstance(item, str):
                        candidates.append(item)
                    scan(item)
            elif isinstance(value, list):
                for item in value:
                    scan(item)

        scan(warm_audit)
        if len(set(candidates)) != 1:
            raise ValueError("cannot identify sealed warm-counter artifact hash")
        warm_expected = candidates[0]
    if sha(warm_counts_path) != warm_expected:
        raise ValueError("sealed warm counters changed")
    bindings = {
        str(p.relative_to(ROOT)): sha(p) for p in (manifest_path, warm_audit_path, warm_counts_path)
    }
    for item in (manifest["source_metadata"], manifest["source_summary"], manifest["artifact"]):
        if sha(ROOT / item["path"]) != item["sha256"]:
            raise ValueError("native provenance binding changed")
        bindings[item["path"]] = item["sha256"]
    for relative, expected in manifest["references"].items():
        if sha(ROOT / relative) != expected:
            raise ValueError(f"native capture reference changed: {relative}")
        bindings[relative] = expected
    shutil.copyfile(manifest_path, out / "inputs/native-manifest.json")
    shutil.copyfile(warm_audit_path, out / "inputs/warm-audit.json")
    grouped = defaultdict(list)
    for meta in manifest["arrays"]:
        grouped[meta["model"], meta["book_id"]].append(meta)
    if len(grouped) != 9:
        raise ValueError("expected exactly nine native model/document conditions")
    documents = []
    checks = []
    with np.load(warm_counts_path) as warm:
        for (model, book), metas in sorted(grouped.items()):
            metas.sort(key=lambda m: m["layer_one_based"])
            if [m["layer_one_based"] for m in metas] != list(range(1, 33)):
                raise ValueError("expected all32 layers")
            chunks, futures = [], []
            for meta in metas:
                path = ROOT / meta["source_path"]
                if sha(path) != meta["source_sha256"]:
                    raise ValueError("native selector bytes changed")
                bindings[meta["source_path"]] = meta["source_sha256"]
                with np.load(path) as source:
                    selected = source["selected_blocks"]
                if list(selected.shape) != meta["source_shape"]:
                    raise ValueError("native selector shape changed")
                incidence = engine.incidence_from_selected(selected, 32512)
                counts = incidence.reshape(127, 256, 508).sum(axis=1).astype(np.uint16)
                if not np.array_equal(counts, warm[meta["key"]]):
                    raise ValueError(
                        "new query union differs from sealed complete-history counters"
                    )
                # Explicit raw-query checks at both M boundaries and causal block transitions.
                for query in (31999, 32000, 32063, 32255, 32256, 32319, 32511):
                    raw = set(map(int, selected[:, query].ravel())) - {-1}
                    if raw != set(map(int, np.flatnonzero(incidence[query]))):
                        raise ValueError("native head union or query order mismatch")
                chunks.append(counts)
                futures.append(incidence[32000:32512])
                checks.append(
                    dict(
                        key=meta["key"],
                        source_sha256=meta["source_sha256"],
                        causal_indices=True,
                        union_equal=True,
                        warm_counts_equal=True,
                    )
                )
            relative = f"inputs/{model}-{book}.npz"
            np.savez_compressed(
                out / relative, chunks=np.asarray(chunks), future=np.asarray(futures)
            )
            documents.append(dict(model=model, book_id=book, input=relative))
            print("Prepared native queries", model, book, flush=True)
    # Independently match first-L checkpoint ranking to deployed top_blocks.
    sys.path.insert(0, str(ROOT / "python"))
    from moonkvsim.aegiskv.current.policy import top_blocks

    comparisons = 0
    for document in documents:
        with np.load(out / document["input"]) as data:
            for checkpoint in (32000, 32256):
                counts = np.zeros((32, 508), dtype=float)
                inc = [() for _ in range(4)]
                for index in range(checkpoint // 256):
                    counts = (counts + data["chunks"][:, index]) * 0.9
                    for layer in range(4):
                        expected = top_blocks(
                            {(layer, b): float(counts[layer, b]) for b in range((index + 1) * 4)},
                            layer,
                            (index + 1) * 4,
                            16,
                            incumbent=inc[layer],
                            hysteresis=0.1,
                        )
                        actual = engine.topk(counts[layer], inc[layer], 16, (index + 1) * 4, 0.1)
                        if actual != expected:
                            raise ValueError("checkpoint ranking differs from deployed policy")
                        inc[layer] = actual
                        comparisons += 1
    write_json(out / "INPUT_BINDINGS.json", bindings)
    write_json(
        out / "INPUT_AUDIT.json",
        dict(
            status="PASS",
            arrays=checks,
            native_query_checks=288 * 7,
            deployed_topk_comparisons=comparisons,
            documents=documents,
            new_native_forwards=0,
        ),
    )
    source_paths = [
        Path(__file__),
        ENGINE,
        ROOT / "tests/aegiskv/test_native_transfer_component.py",
        ROOT / "python/moonkvsim/aegiskv/current/policy.py",
        ROOT / "benchmark/AegisKV/experiments/scripts/current_design/analyze_native_topk_warm.py",
    ]
    source_hashes = {}
    for path in source_paths:
        relative = path.relative_to(ROOT)
        destination = out / "source_snapshot" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        source_hashes[str(relative)] = sha(destination)
    write_json(
        out / "MANIFEST.json",
        dict(
            source_sha256=source_hashes,
            python=platform.python_version(),
            numpy=np.__version__,
            evidence="native-selection-driven raw-KV transfer component simulation",
            timing=(
                "declared H2D bandwidth plus uncalibrated per-layer compute scan; no Qwen profile"
            ),
            physical_execution=False,
            native_recovery_execution=False,
        ),
    )
    paths = [p for p in out.rglob("*") if p.is_file()]
    write_json(
        out / "PREPARED.json",
        dict(
            prepared_utc=datetime.now(UTC).isoformat(),
            sha256={str(p.relative_to(out)): sha(p) for p in sorted(paths)},
        ),
    )


def verify(out):
    prepared = read(out / "PREPARED.json")
    for name, expected in prepared["sha256"].items():
        if sha(out / name) != expected:
            raise ValueError(f"prepared input/source changed: {name}")
    hashes = read(out / "MANIFEST.json")["source_sha256"]
    for path in (Path(__file__).resolve(), ENGINE):
        if hashes[str(path.relative_to(ROOT))] != sha(path):
            raise ValueError("executing source differs from frozen copy")
    return sha(out / "PREPARED.json")


def run(out):
    seal = verify(out)
    if (out / "COMPLETE.json").exists():
        raise FileExistsError("preserve completed component results")
    case_dir = out / "cases"
    case_dir.mkdir(exist_ok=True)
    p = read(out / "PROTOCOL.json")
    results, layer_results, prepared_rows = [], [], []
    for document in read(out / "INPUT_AUDIT.json")["documents"]:
        with np.load(out / document["input"]) as data:
            chunks, future_all = data["chunks"], data["future"]
        for checkpoint in p["M"]:
            offset = checkpoint - 32000
            future = future_all[:, offset : offset + 256]
            prepared, background, _counts = engine.placements(chunks, future, checkpoint)
            background_hash = hashlib.sha256(
                np.asarray(background, dtype=np.int16).tobytes()
            ).hexdigest()
            for method in p["methods"]:
                for layer in range(4):
                    prepared_rows.append(
                        dict(
                            **document,
                            M=checkpoint,
                            method=method,
                            layer=layer + 1,
                            block_ids=" ".join(
                                str(b)
                                for layer_id, b in sorted(prepared[method])
                                if layer_id == layer
                            ),
                        )
                    )
                for bandwidth in p["bandwidth_GBps"]:
                    for compute in p["layer_compute_ns"]:
                        identity = (
                            f"{document['model']}-{document['book_id']}-M{checkpoint}"
                            f"-{method}-B{bandwidth}-C{compute}"
                        )
                        relative = f"cases/{identity}.npz"
                        result_path = case_dir / f"{identity}.json"
                        if result_path.exists():
                            row = read(result_path)
                            if row["prepared_sha256"] != seal or row["trace_sha256"] != sha(
                                out / relative
                            ):
                                raise ValueError("reused component case changed")
                            with np.load(out / relative) as archive:
                                layer = archive["layers"]
                        else:
                            summary, query, layer, segments = engine.simulate(
                                future, checkpoint, prepared[method], background, bandwidth, compute
                            )
                            np.savez_compressed(
                                out / relative,
                                queries=query,
                                layers=layer,
                                transfer_segments=segments,
                            )
                            row = dict(
                                model=document["model"],
                                book_id=document["book_id"],
                                M=checkpoint,
                                method=method,
                                bandwidth_GBps=bandwidth,
                                layer_compute_ns=compute,
                                **summary,
                                background_order_sha256=background_hash,
                                trace=relative,
                                trace_sha256=sha(out / relative),
                                prepared_sha256=seal,
                            )
                            write_json(result_path, row)
                        results.append(row)
                        for index, values in enumerate(layer):
                            layer_results.append(
                                dict(
                                    model=row["model"],
                                    book_id=row["book_id"],
                                    M=checkpoint,
                                    method=method,
                                    bandwidth_GBps=bandwidth,
                                    layer_compute_ns=compute,
                                    layer=index + 1,
                                    **dict(
                                        zip(engine.LAYER_COLUMNS, map(int, values), strict=True)
                                    ),
                                )
                            )
        print(
            "Simulated native document",
            document["model"],
            document["book_id"],
            len(results),
            flush=True,
        )
    if len(results) != p["scenarios"]:
        raise ValueError("incomplete prespecified matrix")
    keys = ("model", "book_id", "M", "bandwidth_GBps", "layer_compute_ns")
    baseline = {tuple(r[k] for k in keys): r for r in results if r["method"] == "DRAM"}
    for row in results:
        base = baseline[tuple(row[k] for k in keys)]
        if row["background_order_sha256"] != base["background_order_sha256"]:
            raise ValueError("variant changes common background order")
        row["gain_vs_dram_ns"] = base["raw_component_finish_ns"] - row["raw_component_finish_ns"]
        row["bytes_saved_vs_dram"] = base["transferred_bytes"] - row["transferred_bytes"]
    grouped = defaultdict(list)
    for row in results:
        grouped[
            row["model"], row["M"], row["method"], row["bandwidth_GBps"], row["layer_compute_ns"]
        ].append(row)
    aggregates = []
    for key, values in sorted(grouped.items()):
        if len(values) != 3:
            raise ValueError("document statistical unit changed")
        aggregate = dict(
            zip(("model", "M", "method", "bandwidth_GBps", "layer_compute_ns"), key, strict=True)
        )
        aggregate["documents"] = 3
        for metric in (
            "raw_component_finish_ns",
            "exposed_wait_ns",
            "gain_vs_dram_ns",
            "transferred_bytes",
            "bytes_saved_vs_dram",
            "transferred_but_not_demanded_bytes",
            "query_ready_wait_mean_ns",
        ):
            aggregate[metric + "_mean"] = mean(r[metric] for r in values)
            aggregate[metric + "_min"] = min(r[metric] for r in values)
            aggregate[metric + "_max"] = max(r[metric] for r in values)
        aggregates.append(aggregate)
    write_csv(out / "document-results.csv", results)
    write_csv(out / "layer-results.csv", layer_results)
    write_csv(out / "prepared-residency.csv", prepared_rows)
    write_csv(out / "summary.csv", aggregates)
    write_json(out / "summary.json", aggregates)
    write_json(
        out / "ARRAY_SCHEMA.json",
        dict(
            queries=dict(
                shape=[32, 256, len(engine.QUERY_COLUMNS)],
                columns=engine.QUERY_COLUMNS,
                indices="layer0..31, query M..M+255; integer ns/counts",
            ),
            layers=dict(shape=[32, len(engine.LAYER_COLUMNS)], columns=engine.LAYER_COLUMNS),
            transfer_segments=dict(
                columns=engine.SEGMENT_COLUMNS,
                semantics=(
                    "physical raw-KV object segments, partial service preserved; bytes "
                    "transferred=end-start times GBps"
                ),
            ),
        ),
    )
    write_json(
        out / "AUDIT.json",
        dict(
            status="PASS",
            scenarios=len(results),
            per_query_records=len(results) * 32 * 256,
            per_layer_records=len(layer_results),
            independent_documents_per_model=3,
            prepared_sha256=seal,
            common_background_checked=True,
            negative_gain_cases=sum(
                r["gain_vs_dram_ns"] < 0 for r in results if r["method"] != "DRAM"
            ),
            zero_gain_cases=sum(
                r["gain_vs_dram_ns"] == 0 for r in results if r["method"] != "DRAM"
            ),
            new_native_forwards=0,
            current_runtime_modified=False,
            output_scope="raw-KV transfer component; no native WCT/full-recovery claim",
        ),
    )
    verify(out)
    paths = [
        path for path in out.rglob("*") if path.is_file() and "source_snapshot" not in path.parts
    ]
    write_json(
        out / "COMPLETE.json",
        dict(
            completed_utc=datetime.now(UTC).isoformat(),
            prepared_sha256=seal,
            scenarios=len(results),
            sha256={str(path.relative_to(out)): sha(path) for path in sorted(paths)},
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "verify"))
    parser.add_argument("--out", type=Path, default=BASE / "native-transfer-postreview-v1")
    args = parser.parse_args()
    out = args.out.resolve()
    if args.command == "prepare":
        prepare(out)
    elif args.command == "run":
        run(out)
    else:
        verify(out)
        if (out / "COMPLETE.json").exists():
            complete = read(out / "COMPLETE.json")
            if complete["prepared_sha256"] != sha(out / "PREPARED.json"):
                raise ValueError("completion/preparation binding changed")
            for name, expected in complete["sha256"].items():
                if sha(out / name) != expected:
                    raise ValueError(f"component output changed: {name}")
        print("Frozen native-transfer source/input/output hashes PASS")


if __name__ == "__main__":
    main()
