#!/usr/bin/env python3
"""Audit the focused AegisKV Store-transport matrix and SVG."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from moonkvsim.aegiskv.transport_preview_figures import (
    TransportPreviewError,
    audit_transport_preview,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit E2 transport results, provenance, and figure bindings."
    )
    parser.add_argument("--matrix-dir", type=Path, required=True)
    parser.add_argument("--figure-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = audit_transport_preview(
            matrix_dir=args.matrix_dir.resolve(),
            figure_dir=args.figure_dir.resolve(),
        )
    except (OSError, ValueError, TransportPreviewError) as error:
        print(f"AegisKV transport preview audit rejected: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
