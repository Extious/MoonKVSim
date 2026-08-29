"""Normalize the Weka JSONL trace or run the same pipeline without writing output."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

if __package__:
    from ._weka import WekaTraceError, audit_weka_trace, normalize_weka_trace
else:
    from _weka import WekaTraceError, audit_weka_trace, normalize_weka_trace


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="raw Weka traces.materialized.jsonl")
    parser.add_argument("--output", type=Path, help="canonical normalized JSONL path")
    parser.add_argument("--manifest-output", type=Path, help="normalizer manifest/audit path")
    parser.add_argument("--expected-raw-sha256", help="fail unless the raw bytes match this hash")
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="read and validate the raw trace without creating normalized data",
    )
    parser.add_argument("--overwrite", action="store_true", help="replace explicit output paths")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.audit_only:
            if args.output is not None or args.manifest_output is not None or args.overwrite:
                raise WekaTraceError(
                    "--audit-only is strictly read-only; output and overwrite flags are forbidden"
                )
            result = audit_weka_trace(
                args.input, expected_raw_sha256=args.expected_raw_sha256
            )
        else:
            if args.output is None:
                raise WekaTraceError("--output is required unless --audit-only is selected")
            result = normalize_weka_trace(
                args.input,
                args.output,
                expected_raw_sha256=args.expected_raw_sha256,
                manifest_path=args.manifest_output,
                overwrite=args.overwrite,
            )
    except (OSError, ValueError) as error:
        print(str(error))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
