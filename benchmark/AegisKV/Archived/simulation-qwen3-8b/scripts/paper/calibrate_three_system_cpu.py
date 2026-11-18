"""Bind measured reference admission CPU quotes, not native serving CPU."""

import argparse
import gzip
import json
import platform
from pathlib import Path

import numpy as np
from three_system_data import SYSTEMS, sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = {
        "schema": "moonkvsim.reference_cpu_quotes.v1",
        "admission_ns": {},
        "samples": {},
        "input_bindings": {},
        "foreground_lookup_ns": 50_000,
        "foreground_lookup_scope": "assumed_common_50us_control_service_not_a_measurement",
        "cpu_queue_model": "one_shared_serial_controller_per_simulated_cluster",
        "quote": "arithmetic_mean_reference_admission_thread_time_per_attempt",
        "scope": "Python_reference_policy_only_not_native_Mooncake_or_AegisKV_serving",
        "cpu_identity": platform.processor(),
        "python": platform.python_version(),
    }
    for s in SYSTEMS:
        raw = args.input / f"{s}.json.gz"
        manifest = json.loads((args.input / f"{s}.manifest.json").read_text())
        assert sha(raw) == manifest["raw_sha256"]
        result.setdefault("source_snapshot_sha256", manifest["source_snapshot_sha256"])
        assert result["source_snapshot_sha256"] == manifest["source_snapshot_sha256"]
        with gzip.open(raw, "rt") as f:
            data = json.load(f)
        values = [r["cpu_ns"] for r in data["representative"]["mechanism"]["policy_cpu"]]
        result["admission_ns"][s] = round(float(np.mean(values)))
        result["samples"][s] = {
            "count": len(values),
            "total_ns": sum(values),
            "p50_ns": float(np.percentile(values, 50)),
            "p95_ns": float(np.percentile(values, 95)),
            "p99_ns": float(np.percentile(values, 99)),
            "max_ns": max(values),
        }
        result["input_bindings"][str(raw.resolve())] = sha(raw)
        del data
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
