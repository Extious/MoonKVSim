#!/usr/bin/env python3
"""Generate the offline AegisKV Store-node sensitivity preview SVG."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from moonkvsim.aegiskv.experiment_config import repository_root
from moonkvsim.aegiskv.store_node_preview_figures import (
    StoreNodePreviewError,
    generate_store_node_preview,
)

ROOT = repository_root()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render one E2 modeled Store-node figure without running a simulator."
    )
    parser.add_argument("--matrix-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    source = ROOT / "python/moonkvsim/aegiskv/store_node_preview_figures.py"
    try:
        result = generate_store_node_preview(
            matrix_dir=args.matrix_dir.resolve(),
            output_dir=args.output_dir.resolve(),
            generator_source=source,
        )
    except (OSError, ValueError, StoreNodePreviewError) as error:
        print(f"AegisKV Store-node preview rejected: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": "PASS",
                "figure": result.figure_path.as_posix(),
                "manifest_sha256": result.manifest_sha256,
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
