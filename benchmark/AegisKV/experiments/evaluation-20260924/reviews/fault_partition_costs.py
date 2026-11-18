"""Raw forward service arithmetic only: no DES or queue counterfactual is run."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924"
sys.path.insert(0, str(ROOT / "python"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def metadata(path):
    values = json.loads(gzip.decompress(path.read_bytes()))
    return {
        (agent["workflow"] + "/" + agent["name"], index): {
            "prompt": len(inv["prompt"]),
            "output": len(inv["output"]),
            "model": inv["model"],
        }
        for agent in values
        for index, inv in enumerate(agent["calls"])
    }


def profile_loader(campaign):
    path = campaign / "source_snapshot/python/moonkvsim/aegiskv/evaluation_profile.py"
    manifest = read(campaign / "MANIFEST.json")
    for name, expected_hash in manifest["control_sha256"].items():
        assert sha(campaign / name) == expected_hash
    expected = manifest["source_sha256"]["python/moonkvsim/aegiskv/evaluation_profile.py"]
    assert sha(path) == expected
    name = "moonkvsim.aegiskv.factcheck_frozen_profile"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.GridDurationProfile


def partition(inv, config, profile, trigger=None):
    cursor, rows = 0, []
    total = inv["prompt"] + inv["output"]
    while cursor < total:
        stage = "prefill" if cursor < inv["prompt"] else "decode"
        chunk = (
            config["prefill_chunk_tokens"] if stage == "prefill" else config["decode_batch_tokens"]
        )
        end = min(
            cursor + chunk,
            (cursor // config["checkpoint_tokens"] + 1) * config["checkpoint_tokens"],
            inv["prompt"] if stage == "prefill" else total,
        )
        if trigger is not None and cursor < trigger < end:
            end = trigger
        cost = profile.duration(
            cursor, end, stage, config["prefill_chunk_tokens"], config["checkpoint_tokens"]
        )
        rows.append({"start": cursor, "end": end, "stage": stage, "service_ns": cost})
        cursor = end
    return rows


def split_cost(inv, config, profile, trigger):
    normal = partition(inv, config, profile)
    split = partition(inv, config, profile, trigger)
    changed = next((r for r in normal if r["start"] < trigger < r["end"]), None)
    fragments = [r for r in split if changed and changed["start"] <= r["start"] < changed["end"]]
    return dict(
        prompt_tokens=inv["prompt"],
        output_tokens=inv["output"],
        logical_trigger=trigger,
        stage="prefill" if trigger < inv["prompt"] else "decode_or_boundary",
        baseline_forward=changed,
        split_fragments=fragments,
        normal_service_ns=sum(r["service_ns"] for r in normal),
        split_only_service_ns=sum(r["service_ns"] for r in split),
        extra_service_ns=sum(r["service_ns"] for r in split) - sum(r["service_ns"] for r in normal),
    )


def main():
    campaign = BASE / "formal-core-v1"
    plan, manifest = read(campaign / "PLAN.json"), read(campaign / "MANIFEST.json")
    loader = profile_loader(campaign)
    profiles, workloads, rows = {}, {}, {}
    for job in plan["jobs"]:
        fault = job["failure"]
        if fault is None:
            continue
        model = job["model"]
        if model not in profiles:
            path = campaign / f"profiles/{model}.json"
            assert sha(path) == manifest["profile_sha256"][f"profiles/{model}.json"]
            profiles[model] = loader(path)
        key = model, fault["agent"], fault["invocation"], fault["progress"]
        if key not in rows:
            name = job["workload"]
            if name not in workloads:
                path = campaign / plan["workloads"][name]["path"]
                assert sha(path) == plan["workloads"][name]["sha256"]
                workloads[name] = metadata(path)
            inv = workloads[name][fault["agent"], fault["invocation"]]
            trigger = math.ceil((inv["prompt"] + inv["output"]) * fault["progress"])
            rows[key] = dict(
                model=model,
                agent=fault["agent"],
                invocation=fault["invocation"],
                fault_index=job["fault_index"],
                **split_cost(inv, job["config"], profiles[model], trigger),
                matching_planned_run_ids=[],
            )
        rows[key]["matching_planned_run_ids"].append(job["id"])
    sensitivity = BASE / "sensitivity-campaign-v1"
    sens = read(sensitivity / "PLAN.json")
    work = sensitivity / sens["workload"]["path"]
    assert sha(work) == sens["workload"]["sha256"]
    invocations = metadata(work)
    sens_manifest = read(sensitivity / "MANIFEST.json")
    sens_profile_path = sensitivity / sens["profile"]
    assert sha(sens_profile_path) == sens_manifest["profile_sha256"]
    sens_profile = profile_loader(sensitivity)(sens_profile_path)
    configs = {
        j["config"]["checkpoint_tokens"]: j["config"]
        for j in sens["jobs"]
        if j["condition"] == "center" or j["config"]["checkpoint_tokens"] == 64
    }
    schedules = {}
    for z, config in configs.items():
        partitions = [
            r for inv in invocations.values() for r in partition(inv, config, sens_profile)
        ]
        schedules[z] = dict(
            checkpoint_tokens=z,
            prefill_chunk_tokens=config["prefill_chunk_tokens"],
            prefill_forwards=sum(r["stage"] == "prefill" for r in partitions),
            prefill_service_ns=sum(r["service_ns"] for r in partitions if r["stage"] == "prefill"),
            total_service_ns=sum(r["service_ns"] for r in partitions),
        )
    result = dict(
        evidence="offline arithmetic on frozen profile and forward partition; no DES executions",
        interpretation=(
            "extra split-only service is shared by policies; not a WCT or queue counterfactual"
        ),
        paper_sha256=sha(ROOT / "benchmark/AegisKV/paper/evaluation.tex"),
        primary_plan_sha256=sha(campaign / "PLAN.json"),
        primary_fixed_faults=list(rows.values()),
        sensitivity_plan_sha256=sha(sensitivity / "PLAN.json"),
        sensitivity_52_invocation_nominal_service=schedules,
        z64_extra_prefill_service_ns=schedules[64]["prefill_service_ns"]
        - schedules[256]["prefill_service_ns"],
        source_sha256=sha(Path(__file__)),
    )
    Path(__file__).with_suffix(".json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    for row in rows.values():
        print(
            row["model"],
            row["fault_index"],
            row["stage"],
            row["logical_trigger"],
            "extra ms",
            row["extra_service_ns"] / 1e6,
        )
    print("Z schedules", schedules)


if __name__ == "__main__":
    main()
