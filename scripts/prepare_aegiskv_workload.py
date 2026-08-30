#!/usr/bin/env python3
"""Create the frozen real-trace input used by AegisKV E2 experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from moonkvsim.aegiskv.experiment_workload import prepare_experiment_workload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "benchmark/AegisKV/experiments/workloads/weka-e2-two-workflow-shapes.jsonl"
        ),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(
            "benchmark/AegisKV/experiments/workloads/weka-e2-two-workflow-manifest.json"
        ),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    manifest = prepare_experiment_workload(
        source_path=args.source,
        output_path=args.output,
        manifest_path=args.manifest,
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
