#!/usr/bin/env python3
"""Execute one strict, fixed-GPU-failure real-trace E2 harness."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from moonkvsim.baseline.e2_harness import (
    E2HarnessError,
    load_harness_config,
    run_harness,
)
from moonkvsim.baseline.trace_runner import TraceRunnerError, TraceRunStatus


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the independent, uncalibrated fixed-GPU-failure E2 trace harness. "
            "PASS exits 0, an honest runtime BLOCKED result exits 3, and "
            "input/invariant errors exit 2."
        )
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_harness_config(args.config)
        if not config.failure_enabled:
            raise E2HarnessError(
                "failure CLI requires an enabled fixed_virtual_time_gpu_fail_stop config"
            )
        outcome = run_harness(config, args.output)
    except (OSError, ValueError, E2HarnessError, TraceRunnerError) as error:
        print(
            json.dumps(
                {
                    "schema": "moonkvsim.vanilla-failure-trace-e2-harness-error.v1",
                    "status": "ERROR",
                    "message": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(outcome.to_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if outcome.result.status is TraceRunStatus.PASS else 3


if __name__ == "__main__":
    raise SystemExit(main())
