#!/usr/bin/env python3
"""Freeze official NVIDIA ODR ExecutionTrace files for MoonKVSim."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from moonkvsim.aegiskv.odr import (
    ODRDurationModel,
    prepare_odr_workload,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize a complete official ODR corpus. This command never changes "
            "requests.json and never launches an experiment."
        )
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--source-license", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expected-task-count", type=int, default=100)
    parser.add_argument("--minimum-task-count-for-ecdf", type=int, default=30)
    parser.add_argument("--max-model-len-tokens", type=int, default=131_072)
    parser.add_argument(
        "--prefill-ns-per-token",
        type=int,
        help="Required with --decode-ns-per-token when compact traces omit timings.",
    )
    parser.add_argument(
        "--decode-ns-per-token",
        type=int,
        help="Required with --prefill-ns-per-token when compact traces omit timings.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if (args.prefill_ns_per_token is None) != (args.decode_ns_per_token is None):
        print(
            "ODR preparation rejected: prefill and decode duration rates must be set together",
            file=sys.stderr,
        )
        return 2
    try:
        duration_model = (
            None
            if args.prefill_ns_per_token is None
            else ODRDurationModel(
                prefill_ns_per_token=args.prefill_ns_per_token,
                decode_ns_per_token=args.decode_ns_per_token,
            )
        )
        manifest = prepare_odr_workload(
            source=args.source,
            output_path=args.output,
            manifest_path=args.manifest,
            source_revision=args.source_revision,
            source_license=args.source_license,
            expected_task_count=args.expected_task_count,
            minimum_task_count_for_ecdf=args.minimum_task_count_for_ecdf,
            duration_model=duration_model,
            max_model_len_tokens=args.max_model_len_tokens,
        )
    except (OSError, ValueError) as error:
        print(f"ODR preparation rejected: {error}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
