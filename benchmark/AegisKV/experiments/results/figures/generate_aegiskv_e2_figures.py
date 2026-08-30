#!/usr/bin/env python3
"""Generate deterministic AegisKV E2 SVGs from a completed matrix bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from moonkvsim.aegiskv.figures import generate_e2_figures


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render E2 modeled/preliminary SVGs from canonical GlobalDES results; "
            "no physical experiment is executed."
        )
    )
    parser.add_argument("--results", type=Path, required=True, help="canonical results.jsonl")
    parser.add_argument("--manifest", type=Path, required=True, help="matrix manifest JSON")
    parser.add_argument(
        "--representative",
        type=Path,
        required=True,
        help="representative-run.json with event timelines",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmark/AegisKV/experiments/results/figures/generated"),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="explicitly replace existing generated targets (default: refuse)",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = generate_e2_figures(
        results_path=args.results,
        manifest_path=args.manifest,
        representative_path=args.representative,
        output_dir=args.output_dir,
        overwrite=args.overwrite,
    )
    summary = {
        "schema": "moonkvsim.aegiskv.figure_generation_summary.v1",
        "status": "PASS",
        "scope": "limited_e2_preview",
        "evidence": "E2 modeled/preliminary; not calibrated; no physical experiment",
        "paper_ready": False,
        "results_sha256": result.results_sha256,
        "matrix_manifest_sha256": result.manifest_sha256,
        "representative_sha256": result.representative_sha256,
        "figure_set_manifest": result.manifest_path.as_posix(),
        "figure_set_manifest_sha256": hashlib.sha256(result.manifest_path.read_bytes()).hexdigest(),
        "artifacts": [
            {
                "figure_id": artifact.figure_id,
                "svg": None if artifact.svg_path is None else artifact.svg_path.as_posix(),
                "provenance": artifact.provenance_path.as_posix(),
            }
            for artifact in result.artifacts
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
