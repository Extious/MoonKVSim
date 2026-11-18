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
from moonkvsim.aegiskv.experiment_config import (
    default_config_dir,
    failure_count,
    load_experiment_configs,
    model_parameters_from_configs,
    repository_root,
    workload_paths,
)
from moonkvsim.aegiskv.experiment_suite import (
    ExperimentSuiteError,
    ImplementationBinding,
    load_frozen_workload,
    run_explicit_e2_matrix,
)

REPOSITORY_ROOT = repository_root()
DEFAULT_CONFIG_DIR = default_config_dir(REPOSITORY_ROOT)
DEFAULT_SEEDS = (0, 1)


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
            "Run modeled Store-node sensitivity from "
            "experiments/configs/{requests,failure,engine}.json; "
            "no physical, CUDA, network, or Slurm path exists."
        )
    )
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--implementation-commit")
    parser.add_argument("--seed", type=int, action="append", dest="seeds")
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
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
            workload_path,
            workload_manifest,
        )
        seeds = DEFAULT_SEEDS if args.seeds is None else tuple(args.seeds)
        output_dir = args.output_dir.resolve()
        manifest = run_explicit_e2_matrix(
            records,
            variants=store_node_sensitivity_variants(parameters),
            workload=workload,
            implementation=implementation,
            output_dir=output_dir,
            protocol_id="aegiskv-store-node-fluid-v1",
            representative_variant_id="store_node_count=4",
            seeds=seeds,
            jobs=args.jobs,
            worker_workload_path=workload_path,
            config_snapshot_dir=configs.directory,
            failure_count=failure_count(configs.failure),
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"AegisKV Store-node matrix rejected: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": "PASS",
                "config_dir": configs.directory.as_posix(),
                "output_dir": output_dir.as_posix(),
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
