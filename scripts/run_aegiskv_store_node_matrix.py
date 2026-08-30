#!/usr/bin/env python3
"""Run the focused CPU-only AegisKV Store-node GlobalDES matrix."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from moonkvsim.aegiskv.experiment import store_node_sensitivity_variants
from moonkvsim.aegiskv.experiment_suite import (
    ExperimentSuiteError,
    ImplementationBinding,
    load_frozen_workload,
    run_explicit_e2_matrix,
)

ROOT = Path(__file__).resolve().parents[1]
WORKLOAD = ROOT / "benchmark/AegisKV/experiments/workloads/weka-e2-two-workflow-shapes.jsonl"
WORKLOAD_MANIFEST = (
    ROOT / "benchmark/AegisKV/experiments/workloads/weka-e2-two-workflow-manifest.json"
)
DEFAULT_SEEDS = (0, 1)


def _git(*args: str) -> str:
    try:
        completed = subprocess.run(
            ("git", *args),
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        raise ExperimentSuiteError(
            f"Git provenance query failed: {detail.strip()}"
        ) from error
    return completed.stdout.strip()


def _implementation_binding(requested_commit: str | None) -> ImplementationBinding:
    head = _git("rev-parse", "HEAD")
    if requested_commit is not None:
        resolved = _git("rev-parse", f"{requested_commit}^{{commit}}")
        if resolved != head:
            raise ExperimentSuiteError(
                f"requested commit resolves to {resolved}, but checkout HEAD is {head}"
            )
    porcelain = _git("status", "--porcelain=v1", "--untracked-files=all")
    if porcelain:
        raise ExperimentSuiteError(
            "focused matrix requires a clean committed worktree:\n"
            + "\n".join(porcelain.splitlines()[:20])
        )
    return ImplementationBinding(
        commit=head,
        tree=_git("rev-parse", "HEAD^{tree}"),
        worktree_clean=True,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run modeled Store-node sensitivity on one global virtual clock; "
            "no physical, CUDA, network, or Slurm path exists."
        )
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--implementation-commit")
    parser.add_argument("--seed", type=int, action="append", dest="seeds")
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        implementation = _implementation_binding(args.implementation_commit)
        records, workload, _manifest = load_frozen_workload(
            WORKLOAD,
            WORKLOAD_MANIFEST,
        )
        seeds = DEFAULT_SEEDS if args.seeds is None else tuple(args.seeds)
        manifest = run_explicit_e2_matrix(
            records,
            variants=store_node_sensitivity_variants(),
            workload=workload,
            implementation=implementation,
            output_dir=args.output_dir.resolve(),
            protocol_id="aegiskv-store-node-fluid-v1",
            representative_variant_id="store_node_count=4",
            seeds=seeds,
            jobs=args.jobs,
            worker_workload_path=WORKLOAD,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"AegisKV Store-node matrix rejected: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": "PASS",
                "output_dir": args.output_dir.resolve().as_posix(),
                "result_count": manifest["result_count"],
                "pair_count": manifest["pair_count"],
                "manifest_fingerprint": manifest["fingerprint"],
                "global_clock": "single_global_virtual_clock",
                "evidence": "E2 modeled/preliminary not_calibrated",
                "physical_execution": False,
                "slurm_used": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
