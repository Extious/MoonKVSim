#!/usr/bin/env python3
"""Freeze the public FanOutQA Evidence-Provided workload for MoonKVSim."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from moonkvsim.aegiskv.fanoutqa import (
    FanOutQADurationModel,
    prepare_fanoutqa_workload,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze exact-revision Wikipedia evidence and exactly 160 complete "
            "FanOutQA workflows. This command never launches an experiment."
        )
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-license", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--tokenizer-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence-snapshot", type=Path, required=True)
    parser.add_argument("--evidence-cache", type=Path, required=True)
    parser.add_argument("--target-task-count", type=int, default=160)
    parser.add_argument("--max-model-len-tokens", type=int, default=131_072)
    parser.add_argument("--prefill-ns-per-token", type=int, default=100_000)
    parser.add_argument("--decode-ns-per-token", type=int, default=5_000_000)
    parser.add_argument("--fetch-workers", type=int, default=16)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = prepare_fanoutqa_workload(
            source_path=args.source,
            license_path=args.source_license,
            tokenizer_snapshot=args.tokenizer_snapshot,
            output_path=args.output,
            manifest_path=args.manifest,
            evidence_snapshot_path=args.evidence_snapshot,
            evidence_cache_dir=args.evidence_cache,
            source_revision=args.source_revision,
            target_task_count=args.target_task_count,
            max_model_len_tokens=args.max_model_len_tokens,
            duration_model=FanOutQADurationModel(
                prefill_ns_per_token=args.prefill_ns_per_token,
                decode_ns_per_token=args.decode_ns_per_token,
            ),
            fetch_workers=args.fetch_workers,
        )
    except (OSError, ValueError) as error:
        print(f"FanOutQA preparation rejected: {error}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
