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

from moonkvsim.aegiskv.experiment_config import (
    default_config_dir,
    load_experiment_configs,
    matrix_seeds,
    model_parameters_from_configs,
    repository_root,
    workload_paths,
)
from moonkvsim.aegiskv.experiment_suite import (
    ExperimentSuiteError,
    ImplementationBinding,
    load_frozen_workload,
    run_e2_matrix,
)

REPOSITORY_ROOT = repository_root()
DEFAULT_CONFIG_DIR = default_config_dir(REPOSITORY_ROOT)


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
            "Run modeled/preliminary AegisKV experiments from "
            "experiments/configs/{requests,failure,engine}.json. "
            "This launcher has no physical, CUDA, network, or Slurm execution path."
        )
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=DEFAULT_CONFIG_DIR,
        help="Directory containing requests.json, failure.json, and engine.json.",
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
        help="Repeat to choose seeds; omitted means requests.json matrix_seeds.",
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
        configs = load_experiment_configs(args.config_dir, root=REPOSITORY_ROOT)
        parameters = model_parameters_from_configs(configs)
        workload_path, workload_manifest = workload_paths(
            configs.requests, root=REPOSITORY_ROOT
        )
        implementation = _implementation_binding(args.implementation_commit)
        records, workload, _manifest = load_frozen_workload(
            workload_path, workload_manifest
        )
        seeds = matrix_seeds(configs.requests) if args.seeds is None else tuple(args.seeds)
        output_dir = args.output_dir.resolve()
        manifest = run_e2_matrix(
            records,
            workload=workload,
            implementation=implementation,
            output_dir=output_dir,
            selection=args.suite,
            seeds=seeds,
            jobs=args.jobs,
            worker_workload_path=workload_path,
            parameters=parameters,
            config_snapshot_dir=configs.directory,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"AegisKV E2 matrix rejected: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": "PASS",
                "suite": args.suite,
                "config_dir": configs.directory.as_posix(),
                "output_dir": output_dir.as_posix(),
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
