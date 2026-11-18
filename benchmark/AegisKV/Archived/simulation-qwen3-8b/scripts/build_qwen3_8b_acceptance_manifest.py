#!/usr/bin/env python3
"""Build the Qwen3-8B paper artifact acceptance manifest."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from moonkvsim.aegiskv.qwen3_8b_acceptance import (
    build_manifest,
    validate_manifest,
    write_json_atomic,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[4],
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=None,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(message)s")
    root = args.repository_root.resolve()
    schema = args.schema or root / "schemas/aegiskv-qwen3-8b-acceptance-manifest.schema.json"
    document = build_manifest(root, args.registry.resolve())
    validate_manifest(document, schema.resolve())
    write_json_atomic(args.output.resolve(), document)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
