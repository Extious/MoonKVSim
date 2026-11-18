#!/usr/bin/env python3
"""Snapshot exact implementation and inputs without committing unrelated edits."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    paths = set((root / "python/moonkvsim").rglob("*.py"))
    paths.update((root / "schemas").glob("*.json"))
    paths.update(p for p in (root / "configs").rglob("*") if p.is_file())
    paths.update((root / "reference").rglob("*.json"))
    paths.update(
        root / name
        for name in (
            "pyproject.toml",
            "benchmark/AegisKV/experiments/scripts/run_agent_lease_mechanisms.py",
            "benchmark/AegisKV/experiments/AGENT_LEASE_PROTOCOL.md",
            "benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/algorithm-2-admission.drawio",
            "benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/algorithm-2-cache-hit.drawio",
            "benchmark/AegisKV/docs/drawio/algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio",
            "uv.lock",
            "benchmark/AegisKV/experiments/scripts/run_three_system_mechanisms.py",
            "benchmark/AegisKV/experiments/scripts/freeze_three_system_source.py",
            "benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-8b-160.jsonl",
            "benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-8b-160-manifest.json",
        )
    )
    bindings = {}
    for path in sorted(paths):
        name = path.relative_to(root)
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        target.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"source changed while snapshotting: {path}")
        bindings[str(name)] = digest
    manifest = {
        "schema": "moonkvsim.mechanism_source_snapshot.v1",
        "files": bindings,
        "git_head_reference_only": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "identity": "exact_working_tree_content_hashes_including_untracked_implementation",
    }
    (output / "MECHANISM_SOURCE_SNAPSHOT.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"snapshot": str(output), "files": len(bindings)}))


if __name__ == "__main__":
    main()
