"""Command-line entry point for MoonKVSim."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from moonkvsim import __version__
from moonkvsim.config import (
    ConfigBundleError,
    SchemaValidationError,
    load_config_bundle,
    validate_file,
    validate_jsonl_trace,
)

_SCHEMA_CHOICES = (
    "deployment",
    "failure",
    "multi-agent-trace",
    "requests",
    "run-manifest",
)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="moonkv-sim")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")
    validate = subparsers.add_parser(
        "validate",
        help="fail-closed validation of a config, manifest, or normalized trace",
    )
    validate.add_argument("path", type=Path)
    validate.add_argument("--schema", choices=_SCHEMA_CHOICES)
    validate.add_argument(
        "--jsonl-trace",
        action="store_true",
        help="stream records and validate cross-span DAG relationships",
    )
    resolve = subparsers.add_parser(
        "resolve-config",
        help="validate one requests/failure/deployment bundle and publish canonical JSON",
    )
    resolve.add_argument("--requests", required=True, type=Path)
    resolve.add_argument("--failure", required=True, type=Path)
    resolve.add_argument("--deployment", required=True, type=Path)
    resolve.add_argument("--output", required=True, type=Path)
    resolve.add_argument("--repository-root", type=Path, default=_REPOSITORY_ROOT)
    resolve.add_argument(
        "--overwrite",
        action="store_true",
        help="explicitly replace an existing resolved config",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "resolve-config":
        try:
            bundle = load_config_bundle(
                args.requests,
                args.failure,
                args.deployment,
                repository_root=args.repository_root,
            )
            bundle.write(args.output, overwrite=args.overwrite)
        except (OSError, ConfigBundleError, SchemaValidationError, ValueError) as error:
            print(str(error))
            return 2
        print(
            json.dumps(
                {
                    "schema": "moonkvsim.resolved_config.v1",
                    "sha256": bundle.sha256,
                    "status": "pass",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    if args.command != "validate":
        return 0
    try:
        if args.jsonl_trace:
            if args.schema is not None:
                raise ValueError("--schema and --jsonl-trace are mutually exclusive")
            result: Mapping[str, object] = validate_jsonl_trace(args.path)
        else:
            document = validate_file(args.path, args.schema)
            result = {"schema": document["schema"], "status": "pass"}
    except (OSError, SchemaValidationError, ValueError) as error:
        print(str(error))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
