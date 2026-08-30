#!/usr/bin/env python3
"""Run the canonical CPU-only AegisKV GlobalDES E2 matrix."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from moonkvsim.aegiskv.experiment_suite import (
    DEFAULT_SEEDS,
    ExperimentSuiteError,
    ImplementationBinding,
    load_frozen_workload,
    run_e2_matrix,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKLOAD = (
    REPOSITORY_ROOT / "benchmark/AegisKV/experiments/workloads/weka-e2-two-workflow-shapes.jsonl"
)
DEFAULT_WORKLOAD_MANIFEST = (
    REPOSITORY_ROOT / "benchmark/AegisKV/experiments/workloads/weka-e2-two-workflow-manifest.json"
)


def _git(*args: str) -> str:
    try:
        completed = subprocess.run(
            ("git", *args),
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        raise ExperimentSuiteError(f"Git provenance query failed: {detail.strip()}") from error
    return completed.stdout.strip()


def _implementation_binding(requested_commit: str | None) -> ImplementationBinding:
    head = _git("rev-parse", "HEAD")
    if requested_commit is not None:
        resolved = _git("rev-parse", f"{requested_commit}^{{commit}}")
        if resolved != head:
            raise ExperimentSuiteError(
                f"--implementation-commit resolves to {resolved}, but checkout HEAD is {head}"
            )
    tree = _git("rev-parse", "HEAD^{tree}")
    porcelain = _git("status", "--porcelain=v1", "--untracked-files=all")
    if porcelain:
        preview = "\n".join(porcelain.splitlines()[:20])
        raise ExperimentSuiteError(
            f"implementation worktree is dirty; commit the exact suite before running:\n{preview}"
        )
    return ImplementationBinding(commit=head, tree=tree, worktree_clean=True)


def _parser() -> argparse.ArgumentParser:
    default_jobs = min(8, os.cpu_count() or 1)
    parser = argparse.ArgumentParser(
        description=(
            "Run modeled/preliminary AegisKV experiments on one global virtual clock. "
            "This launcher has no physical, CUDA, network, or Slurm execution path."
        )
    )
    parser.add_argument("--suite", choices=("core", "all"), default="core")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--implementation-commit",
        help=("Commit that must resolve to the clean checkout HEAD; defaults to the current HEAD."),
    )
    parser.add_argument(
        "--seed",
        type=int,
        action="append",
        dest="seeds",
        help="Repeat to choose seeds; omitted means 0, 1, and 2.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=default_jobs,
        help=f"CPU worker processes (default: {default_jobs}; use 1 for sequential execution).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        implementation = _implementation_binding(args.implementation_commit)
        records, workload, _manifest = load_frozen_workload(
            DEFAULT_WORKLOAD, DEFAULT_WORKLOAD_MANIFEST
        )
        seeds = DEFAULT_SEEDS if args.seeds is None else tuple(args.seeds)
        manifest = run_e2_matrix(
            records,
            workload=workload,
            implementation=implementation,
            output_dir=args.output_dir.resolve(),
            selection=args.suite,
            seeds=seeds,
            jobs=args.jobs,
            worker_workload_path=DEFAULT_WORKLOAD,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"AegisKV E2 matrix rejected: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": "PASS",
                "suite": args.suite,
                "output_dir": args.output_dir.resolve().as_posix(),
                "result_count": manifest["result_count"],
                "pair_count": manifest["pair_count"],
                "manifest_fingerprint": manifest["fingerprint"],
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
