"""Offline healthy compute-start exposure reconstruction; never executes DES."""

from __future__ import annotations

import bisect
import csv
import gzip
import hashlib
import json
import math
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

from moonkvsim.aegiskv.evaluation_profile import GridDurationProfile

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent.parent
ROOT = STUDY.parents[3]
SOURCE = STUDY / "low-dma-postreview-v1"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def rows(path):
    with gzip.open(path, "rt") as stream:
        return [json.loads(line) for line in stream]


def main():
    bindings = {}

    def bind(path, expected=None):
        value = sha(path)
        if expected is not None:
            assert value == expected, str(path)
        bindings[str(path.relative_to(ROOT))] = value

    plan = read(SOURCE / "PLAN.json")
    manifest = read(SOURCE / "MANIFEST.json")
    for name in ("PLAN.json", "MANIFEST.json", "FLOW_AUDIT.json", "PACKAGE_COMPLETE.json"):
        bind(SOURCE / name)
    for name in (
        "python/moonkvsim/aegiskv/evaluation_profile.py",
        "python/moonkvsim/aegiskv/current/runtime.py",
        "python/moonkvsim/aegiskv/current/model.py",
    ):
        bind(ROOT / name, manifest["source_sha256"][name])
        bind(SOURCE / "source_snapshot" / name, manifest["source_sha256"][name])
    workload_path = SOURCE / plan["workload"]["path"]
    bind(workload_path, plan["workload"]["sha256"])
    with gzip.open(workload_path, "rt") as stream:
        workload = json.load(stream)
    agents = {f"{a['workflow']}/{a['name']}": a for a in workload}
    assert len(agents) == 52 and all(len(a["calls"]) == 1 for a in agents.values())
    profile_path = SOURCE / plan["profile"]
    bind(profile_path, manifest["profile_sha256"])
    profile = GridDurationProfile(profile_path)
    output, request_rows = [], []
    for job in plan["jobs"]:
        if job["fault"] != "F0":
            continue
        folder = SOURCE / "runs" / job["id"]
        marker = read(folder / "COMPLETE.json")
        bind(folder / "COMPLETE.json")
        for name, expected in marker["artifact_sha256"].items():
            bind(folder / name, expected)
        summary, config = read(folder / "summary.json"), read(folder / "config.json")
        assert summary["complete"] and not summary["failure"]
        assert not summary["recoveries"] and not summary["history_restores"]
        assert not summary["metrics"].get("primary_admission_waits", 0)
        events = rows(folder / "events.jsonl.gz")
        submitted = {e["agent"]: e for e in events if e["kind"] == "submit"}
        assert len(submitted) == 52
        assert all(e["local_prefix_tokens"] == 0 for e in submitted.values())
        intervals = defaultdict(list)
        for item in rows(folder / "flows.jsonl.gz"):
            assert item["allocated_rate_bytes_per_second"] > 0
            for resource in item["path_resource_ids"]:
                if resource.startswith(("h2d:", "d2h:")):
                    worker = int(resource.split(":")[1])
                    intervals[worker].append((item["start_ns"], item["end_ns"]))
        merged = {}
        for worker, values in intervals.items():
            union = []
            for start, end in sorted(values):
                if end <= start:
                    continue
                if union and start <= union[-1][1]:
                    union[-1][1] = max(union[-1][1], end)
                else:
                    union.append([start, end])
            merged[worker] = ([v[0] for v in union], [v[1] for v in union])
        per_worker = defaultdict(list)
        for request in summary["requests"]:
            per_worker[request["worker"]].append(request)
        counts = defaultdict(int)
        for worker, requests in per_worker.items():
            previous_finish = 0
            starts, ends = merged.get(worker, ([], []))
            for request in sorted(requests, key=lambda r: r["finish_ns"]):
                agent = request["agent"]
                call = agents[agent]["calls"][0]
                assert request["invocation"] == 0
                assert submitted[agent]["time_ns"] == request["submit_ns"]
                admitted = max(request["submit_ns"], previous_finish)
                now, token = admitted, 0
                prompt, total = len(call["prompt"]), len(call["prompt"]) + len(call["output"])
                local = defaultdict(int)
                while token < total:
                    if token < prompt:
                        stage = "prefill"
                        stop = min(
                            token + config["prefill_chunk_tokens"],
                            (token // config["checkpoint_tokens"] + 1) * config["checkpoint_tokens"],
                            prompt,
                        )
                    else:
                        stage = "decode"
                        stop = min(
                            total,
                            token + config["decode_batch_tokens"],
                            (token // config["checkpoint_tokens"] + 1) * config["checkpoint_tokens"],
                        )
                    base = profile.duration(
                        token, stop, stage,
                        config["prefill_chunk_tokens"], config["checkpoint_tokens"],
                    )
                    index = bisect.bisect_right(starts, now) - 1
                    active = index >= 0 and now < ends[index]
                    extra = math.ceil(base * config["compute_dma_slowdown"]) if active else 0
                    local["compute_events"] += 1
                    local["copy_exposed_events"] += int(active)
                    local["base_compute_ns"] += base
                    local["copy_exposed_base_compute_ns"] += base if active else 0
                    local["modeled_extra_compute_ns"] += extra
                    now += base + extra
                    token = stop
                residual = now - request["finish_ns"]
                assert residual == 0, (job["id"], agent, residual)
                previous_finish = now
                for key, value in local.items():
                    counts[key] += value
                request_rows.append(dict(
                    run=job["id"], agent=agent, worker=worker, admitted_ns=admitted,
                    reconstructed_finish_ns=now, retained_finish_ns=request["finish_ns"],
                    **local,
                ))
        assert counts["modeled_extra_compute_ns"] == summary["metrics"].get(
            "modeled_dma_compute_slowdown_ns", 0
        ), (job["id"], counts)
        output.append(dict(
            run=job["id"], coefficient=config["compute_dma_slowdown"], policy=job["policy"],
            **counts,
            copy_exposed_event_fraction=counts["copy_exposed_events"] / counts["compute_events"],
            copy_exposed_compute_fraction=counts["copy_exposed_base_compute_ns"] / counts["base_compute_ns"],
        ))
    for filename, table in (("healthy-compute-exposure.csv", output), ("request-reconstruction.csv", request_rows)):
        with (HERE / filename).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(table[0]))
            writer.writeheader()
            writer.writerows(table)
    # Recompute the two-scenario objective in integer nanoseconds from every
    # retained summary rather than accepting the published decimal ratios.
    provenance_path = SOURCE / "COMBINED_PROVENANCE.json"
    bind(provenance_path)
    data = {}
    target = next(j["failure"]["agent"].split("/")[0] for j in plan["jobs"] if j["fault"] == "F1")
    for filename, expected in read(provenance_path)["source_summary_sha256"].items():
        path = Path(filename)
        bind(path, expected)
        bind(path.parent / "config.json")
        retained = read(path)
        config = read(path.parent / "config.json")
        phase = "F1" if retained["failure"] else "F0"
        key = config["compute_dma_slowdown"], retained["policy"], phase
        assert key not in data
        data[key] = retained
    assert len(data) == 42
    endpoint_rows = []
    for coefficient in sorted({k[0] for k in data}):
        for policy in ("dram", "aegiskv"):
            for endpoint in ("target", "cohort_sum"):
                def value(which_policy, phase):
                    workflows = data[coefficient, which_policy, phase]["workflows"]
                    if endpoint == "target":
                        return workflows[target]["wct_ns"]
                    return sum(w["wct_ns"] for w in workflows.values())

                f0, f1 = value(policy, "F0"), value(policy, "F1")
                h = f0 - value("none", "F0")
                gain = value("none", "F1") - f1
                d = h + gain
                assert h >= 0
                if gain <= 0:
                    label, feasible = "no break-even in [0,1]", ""
                elif h == 0:
                    label, feasible = "equality at p=0; improvement for any p>0", "0"
                else:
                    label, feasible = "equality at threshold; improvement above it", float(Fraction(h, d))
                endpoint_rows.append(dict(
                    coefficient=coefficient, policy=policy, predictor="original_service_proxy",
                    endpoint=endpoint, f0_wct_ns=f0, f1_wct_ns=f1,
                    healthy_cost_ns=h, absolute_f1_gain_ns=gain,
                    fault_increment_saved_ns=d,
                    formal_algebraic_root=str(Fraction(h, d)) if d else "",
                    feasible_probability_threshold=feasible, interpretation=label,
                ))
    with (HERE / "corrected-break-even.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(endpoint_rows[0]))
        writer.writeheader()
        writer.writerows(endpoint_rows)
    table = [
        "# Low-DMA reporting correction and offline dose check", "",
        "This sidecar preserves the sealed original package. No DES was rerun,",
        "no model was tuned and no original numeric artifact was edited.", "",
        "The start-of-compute slowdown is binary: if any active flow uses a",
        "worker's H2D/D2H resource, that event is charged ceil(base duration ×",
        "coefficient). Average payload bytes/s is traffic accounting, not this dose.",
        "The host-rate window is common across hosts within one run; its endpoints",
        "are that run's first release and last completion, so it is not common",
        "across runs and includes idle time.", "",
        "For the 12 fully logged healthy runs, offline profile/flow reconstruction",
        "matches all 624 request completions and each retained total slowdown exactly.",
        "Each run has 2,850 compute events. DRAM and AegisKV have 2,246 exposed",
        "starts at coefficients 0.002/0.005 and 2,245 at 0.01/0.02:",
        "78.81%/78.77% of event starts, representing 75.41%/75.30% of base compute",
        "duration. Restart has zero exposed starts. This verifies the finite",
        "healthy cases only; F1 recovery schedules and older incompletely logged",
        "parameter points do not receive reconstructed fractions.", "",
        "Every table below uses a cohort **sum**. Target objectives remain separate",
        "in corrected-break-even.csv. The accumulated compute-event extra time",
        "is a different quantity from workflow cost, because workers overlap.", "",
        "| coefficient | policy (service proxy) | healthy cost H (s) | absolute F1 gain A (s) | feasible break-even p |",
        "|---:|---|---:|---:|---|",
    ]
    for row in endpoint_rows:
        if row["endpoint"] != "cohort_sum":
            continue
        threshold = row["feasible_probability_threshold"]
        display = "none" if threshold == "" else ("0 (p>0 improves)" if threshold == "0" else f"{threshold:.6f}")
        table.append(
            f"| {row['coefficient']:g} | {row['policy']} | {row['healthy_cost_ns']/1e9:.9f} | "
            f"{row['absolute_f1_gain_ns']/1e9:.9f} | {display} |"
        )
    table += ["", "For this exact two-scenario mixture, net advantage is p(H+A)−H.",
              "At c=0.05/0.1 the absolute faulted cohort gain is negative, so no",
              "probability in [0,1] improves the objective; algebraic roots above one",
              "are retained only in the CSV and are not described as probabilities.",
              "This remains one input-selected longest-prompt fault, four dependent",
              "workflows, and an uncalibrated binary sensitivity. It is not a measured",
              "failure probability, population estimate or physical DMA calibration.", ""]
    (HERE / "README.md").write_text("\n".join(table))
    result = dict(
        status="PASS", healthy_runs=len(output), request_completions_verified=len(request_rows),
        mode="offline timestamp/profile reconstruction, no DES or policy execution",
        definition="Fraction of healthy compute-event starts with a positive recorded flow interval using H2D or D2H on the worker; duration-weighted fraction reported separately.",
        exact_checks="Every reconstructed request finish and per-run accumulated integer slowdown equals the retained artifact.",
        raw_break_even_sources=len(data), corrected_endpoint_rows=len(endpoint_rows),
        limitations=[
            "Healthy F0 only; recovery schedules were not reconstructed.",
            "Twelve new low-DMA F0 runs have full flow logs; older18 points do not uniformly retain them.",
            "No admission memory waits, local reused prefix or repeated-Agent calls in these selected healthy runs.",
            "This is a reconstruction of the binary model dose, not physical GPU interference or measured DMA performance.",
            "Flow interval starts are inclusive and ends exclusive; exact endpoint and total-slowdown equality validate this convention on these runs.",
        ],
        input_sha256=bindings,
    )
    assert all(sha(ROOT / name) == value for name, value in bindings.items())
    (HERE / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ["status", "healthy_runs", "request_completions_verified"]}))


if __name__ == "__main__":
    main()
