#!/usr/bin/env python3
"""Build the accepted Qwen3-8B five-seed paper failure campaign."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from moonkvsim.aegiskv.qwen3_8b_acceptance import write_json_atomic
from moonkvsim.aegiskv.qwen3_8b_failure_campaign import build_campaign, validate_campaign


def _parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[4]
    results = root / "benchmark/AegisKV/experiments/results"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-template",
        default=str(results / "e2-qwen3-8b-paper-f1-v11-seed{seed}.json"),
        help="Python format string containing {seed}",
    )
    parser.add_argument(
        "--classifier-template",
        default=str(results / "e2-qwen3-8b-paper-f1-v11-seed{seed}.direct.json"),
        help="Python format string containing {seed}; missing files are generated",
    )
    parser.add_argument(
        "--classifier-source",
        type=Path,
        default=Path(__file__).with_name("classify_qwen3_8b_direct_recovery.py"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--schema",
        type=Path,
        default=root / "schemas/aegiskv-qwen3-8b-failure-campaign.schema.json",
    )
    parser.add_argument(
        "--allow-deterministic-repeats",
        action="store_true",
        help="Testing/reproducibility only; disables independent-admission requirement",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    artifacts = [
        Path(args.artifact_template.format(seed=seed)).resolve() for seed in range(5)
    ]
    classifiers = [
        Path(args.classifier_template.format(seed=seed)).resolve() for seed in range(5)
    ]
    campaign = build_campaign(
        artifact_paths=artifacts,
        classifier_paths=classifiers,
        classifier_source=args.classifier_source.resolve(),
        require_independent_admission=not args.allow_deterministic_repeats,
    )
    validate_campaign(campaign, args.schema.resolve())
    write_json_atomic(args.output.resolve(), campaign)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
