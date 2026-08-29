#!/usr/bin/env python3
"""Generate or byte-check a source-locked Qwen3-8B ``kv-layout.json``."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from moonkvsim.integration.vllm.kv_layout_artifact import (
    audit_kv_layout_document,
    build_qwen3_kv_layout_document,
    canonical_kv_layout_bytes,
    load_locked_qwen3_layout_inputs,
)


def _partition(value: str) -> tuple[int, ...]:
    try:
        partition = tuple(int(item) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("partition must be comma-separated integers") from error
    if not partition or any(item <= 0 for item in partition):
        raise argparse.ArgumentTypeError("partition entries must be positive")
    return partition


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-lock",
        type=Path,
        default=Path("reference/source-lock.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--context-mode",
        choices=("native", "proposed-yarn-128k"),
        required=True,
    )
    parser.add_argument("--tp-size", type=int, default=1)
    parser.add_argument("--pp-size", type=int, default=1)
    parser.add_argument("--block-size-tokens", type=int, default=16)
    parser.add_argument("--allocator-alignment-bytes", type=int, default=256)
    parser.add_argument(
        "--allocator-metadata-bytes-per-layer-block",
        type=int,
        default=0,
    )
    parser.add_argument(
        "--pp-layer-partition",
        type=_partition,
        help="explicit VLLM_PP_LAYER_PARTITION-equivalent list, for example 18,18",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail unless the existing output is byte-identical to regeneration",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        inputs = load_locked_qwen3_layout_inputs(args.source_lock)
        document = build_qwen3_kv_layout_document(
            inputs,
            context_mode=args.context_mode,
            tp_size=args.tp_size,
            pp_size=args.pp_size,
            block_size_tokens=args.block_size_tokens,
            allocator_alignment_bytes=args.allocator_alignment_bytes,
            allocator_metadata_bytes_per_layer_block=(
                args.allocator_metadata_bytes_per_layer_block
            ),
            pp_layer_partition=args.pp_layer_partition,
        )
        audit_kv_layout_document(document)
        expected = canonical_kv_layout_bytes(document)
        if args.check:
            actual = args.output.read_bytes()
            if actual != expected:
                raise ValueError(f"{args.output} is not byte-identical to regeneration")
            status = "checked"
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(expected)
            status = "generated"
    except (OSError, ValueError) as error:
        print(str(error))
        return 2
    print(
        json.dumps(
            {
                "artifact_fingerprint": document["fingerprint"],
                "context_mode": args.context_mode,
                "evidence_class": "E1",
                "output": str(args.output),
                "status": status,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
