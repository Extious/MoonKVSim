"""Invoke the explicitly requested Cursor Claude Opus 5.5, with input hashes."""

import datetime
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
PAPER = ROOT / "benchmark/AegisKV/paper"
STUDY = HERE.parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs():
    paths = list(PAPER.glob("*.tex")) + list(PAPER.glob("*.bib"))
    paths += [*((PAPER / "figures").glob("eval-*.pdf")), PAPER / "main.pdf"]
    paths += [
        HERE / "candidate-review-prompt.txt",
        STUDY / "PROTOCOL.md",
        STUDY / "LITERATURE_AND_DESIGN.md",
        ROOT / "benchmark/AegisKV/docs/DESIGN_IMPLEMENTATION_COVERAGE.md",
        ROOT / "benchmark/AegisKV/docs/current-design-simulation.md",
        HERE / "REVIEW_DISPOSITION.md",
    ]
    for campaign in (
        "formal-core-v1",
        "structural-campaign-v1",
        "sensitivity-campaign-v1",
        "capacity-slack-ablation-v1",
        "native-topk-warm",
    ):
        for name in ("AUDIT.json", "PLAN.json", "MANIFEST.json", "STATISTICS.json", "RESULTS.md"):
            path = STUDY / campaign / name
            if path.exists():
                paths.append(path)
    paths += list((ROOT / "python/moonkvsim/aegiskv/current").glob("*.py"))
    return {str(path.relative_to(ROOT)): sha(path) for path in sorted(set(paths))}


if __name__ == "__main__":
    binary = "/home/comp/zhanzhao/.local/share/cursor-agent/proxy-bin/cursor-agent"
    before = inputs()
    record = dict(
        started_utc=datetime.datetime.now(datetime.UTC).isoformat(),
        requested_model="claude-opus-5-5-max",
        binary=binary,
        input_sha256=before,
    )
    (HERE / "CANDIDATE_REVIEW_INVOCATION.json").write_text(json.dumps(record, indent=2) + "\n")
    prompt = (HERE / "candidate-review-prompt.txt").read_text()
    with (
        (HERE / "candidate-opus55.jsonl").open("w") as stdout,
        (HERE / "candidate-opus55.stderr").open("w") as stderr,
    ):
        result = subprocess.run(
            [
                binary,
                "--model",
                "claude-opus-5-5-max",
                "--mode",
                "ask",
                "--print",
                "--output-format",
                "stream-json",
                "--trust",
                prompt,
            ],
            cwd=ROOT,
            stdout=stdout,
            stderr=stderr,
        )
    record.update(
        finished_utc=datetime.datetime.now(datetime.UTC).isoformat(),
        exit_code=result.returncode,
        after_sha256=inputs(),
    )
    record["input_drift"] = [
        path
        for path in sorted(set(before) | set(record["after_sha256"]))
        if before.get(path) != record["after_sha256"].get(path)
    ]
    (HERE / "CANDIDATE_REVIEW_INVOCATION.json").write_text(json.dumps(record, indent=2) + "\n")
    (HERE / "candidate-exit.txt").write_text(str(result.returncode) + "\n")
    for line in (HERE / "candidate-opus55.jsonl").read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            record["reported_model"] = event.get("model")
            record["review_session_id"] = event.get("session_id")
        if event.get("type") == "result" and isinstance(event.get("result"), str):
            (HERE / "CANDIDATE_OPUS55.md").write_text(event["result"] + "\n")
            record["review_result_subtype"] = event.get("subtype")
            record["review_is_error"] = event.get("is_error")
    (HERE / "CANDIDATE_REVIEW_INVOCATION.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({key: record[key] for key in ("finished_utc", "exit_code", "input_drift")}))
