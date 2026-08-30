#!/usr/bin/env python3
"""Generate focused fluid/HBM SVG previews from a completed core E2 bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from moonkvsim.aegiskv.fluid_preview_figures import generate_fluid_core_preview


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Render offline E2 GlobalDES fluid/HBM previews; no physical, CUDA, "
            "network, or Slurm execution path exists."
        )
    )
    parser.add_argument("--matrix-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = generate_fluid_core_preview(
        matrix_dir=args.matrix_dir.resolve(),
        output_dir=args.output_dir.resolve(),
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "output_dir": result.output_dir.as_posix(),
                "manifest": result.manifest_path.as_posix(),
                "manifest_sha256": result.manifest_sha256,
                "artifact_count": len(result.artifact_paths),
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
