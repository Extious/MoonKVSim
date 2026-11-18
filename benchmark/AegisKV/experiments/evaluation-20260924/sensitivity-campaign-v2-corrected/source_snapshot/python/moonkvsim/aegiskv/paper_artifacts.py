"""Portable, atomic raw evidence for simulation-only paper experiments."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from moonkvsim.common.hash import sha256_json


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_raw_evidence(path: Path, document: Mapping[str, Any]) -> dict[str, str]:
    """Stream complete evidence; deterministic gzip and atomic publication.

    Compression level one reduces serialization cost for large scheduler and
    resource event streams. No event or span is dropped to reduce output size.
    The returned path is portable relative to the enclosing proof directory.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as raw:
            temporary = Path(raw.name)
            with (
                gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=1) as gz,
                io.TextIOWrapper(gz, encoding="utf-8") as text,
            ):
                json.dump(
                    document, text, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False, allow_nan=False,
                )
                text.write("\n")
            raw.flush()
            os.fsync(raw.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return {"file": path.name, "sha256": file_sha256(path)}


def load_raw_evidence(path: Path, *, expected_sha256: str) -> dict[str, Any]:
    if file_sha256(path) != expected_sha256:
        raise ValueError(f"raw evidence checksum mismatch: {path}")
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("raw evidence must be a JSON object")
    return value


def verify_compact_run(raw: Mapping[str, Any], compact: Mapping[str, Any]) -> None:
    """Bind every retained summary metric and impacted span to full raw evidence."""
    if raw.get("schema") != "moonkvsim.aegiskv.paper_raw_run.v1":
        raise ValueError("unsupported paper raw schema")
    for field in ("payload", "span_details", "representative"):
        if sha256_json(raw[field]) != compact.get(f"{field}_sha256"):
            raise ValueError(f"raw {field} hash disagrees with compact run")
    if raw["journal_sha256"] != compact.get("journal_sha256"):
        raise ValueError("raw journal binding disagrees with compact run")
    payload = raw["payload"]
    for field in ("workflow_admission", "randomization"):
        if payload[field] != compact.get(field):
            raise ValueError(f"compact {field} disagrees with raw evidence")
    for field, value in compact["metrics"].items():
        if payload["metrics"].get(field) != value:
            raise ValueError(f"compact metric disagrees with raw evidence: {field}")
    details = {item["span_id"]: item for item in raw["span_details"]}
    expected = {key for key, item in details.items() if item["failure_at_ns"] is not None}
    impacted = compact["failure_impacted_spans"]
    if len(impacted) != len(expected) or {item["span_id"] for item in impacted} != expected:
        raise ValueError("compact impacted-span population disagrees with raw evidence")
    routes = {
        item["span_id"]: item for item in raw["representative"]["route_events"]
        if item["route_version"] > 0
    }
    for item in impacted:
        for key, value in item.items():
            if key in details[item["span_id"]] and details[item["span_id"]][key] != value:
                raise ValueError(f"compact impacted-span value changed: {key}")
        route = routes[item["span_id"]]
        for compact_key, raw_key in (
            ("available_peer_tokens_at_failure", "peer_prefix_tokens_by_gpu"),
            ("available_normal_hbm_tokens_at_failure", "normal_hbm_prefix_tokens_by_gpu"),
        ):
            if item[compact_key] != route[raw_key][route["selected_gpu_id"]]:
                raise ValueError(f"compact route-bound prefix changed: {compact_key}")
        if item["available_store_tokens_at_failure"] != route["store_prefix_tokens"]:
            raise ValueError("compact Store prefix changed")
    by_id = {item["span_id"]: item for item in impacted}
    focus = compact["failure_focus_spans"]
    expected_focus = {item["focus_span_id"] for item in payload["failure_schedule"]["events"]}
    if len(focus) != len(expected_focus) or {item["span_id"] for item in focus} != expected_focus:
        raise ValueError("compact focus population differs from its declared intervention")
    if any(item != by_id[item["span_id"]] for item in focus):
        raise ValueError("compact focus differs from raw impacted-span evidence")
