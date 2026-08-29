"""Read-only audit of Weka coverage under the full 131072-token model guard."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

if __package__:
    from ._weka import WekaTraceError, _write_json_atomic, audit_weka_trace
else:
    from _weka import WekaTraceError, _write_json_atomic, audit_weka_trace


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="raw Weka traces.materialized.jsonl")
    parser.add_argument("--output", type=Path, help="optional small JSON audit report")
    parser.add_argument("--expected-raw-sha256", help="fail unless the raw bytes match this hash")
    parser.add_argument(
        "--raw-trace-read-only",
        action="store_true",
        help="assert raw size, mtime, and inode are unchanged by the audit",
    )
    parser.add_argument("--overwrite", action="store_true", help="replace only --output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    before = args.input.stat() if args.raw_trace_read_only else None
    try:
        result = audit_weka_trace(args.input, expected_raw_sha256=args.expected_raw_sha256)
        if before is not None:
            after = args.input.stat()
            before_identity = (before.st_ino, before.st_size, before.st_mtime_ns)
            after_identity = (after.st_ino, after.st_size, after.st_mtime_ns)
            if before_identity != after_identity:
                raise WekaTraceError("raw trace changed during read-only audit")
        if args.output is not None:
            if args.output.resolve() == args.input.resolve():
                raise WekaTraceError("audit output cannot overwrite the raw trace")
            _write_json_atomic(args.output, result, overwrite=args.overwrite)
    except (OSError, ValueError) as error:
        print(str(error))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
