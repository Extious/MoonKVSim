#!/usr/bin/env python3
"""Audit the AegisKV fluid-core matrix and focused SVG preview bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from moonkvsim.aegiskv.fluid_preview_figures import (
    FluidPreviewError,
    audit_fluid_core_preview,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Offline audit of GlobalDES E2 fluid/HBM previews; no simulator, physical, "
            "CUDA, network, or Slurm execution path exists."
        )
    )
    parser.add_argument("--matrix-dir", required=True, type=Path)
    parser.add_argument("--figure-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        audit = audit_fluid_core_preview(
            matrix_dir=args.matrix_dir.resolve(),
            figure_dir=args.figure_dir.resolve(),
        )
    except (OSError, FluidPreviewError) as error:
        print(f"AegisKV fluid preview audit rejected: {error}", file=sys.stderr)
        return 2
    print(json.dumps(audit.to_dict(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
