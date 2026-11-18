"""Bound a read-only Opus review to completed remediation inputs."""

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent.parent
ROOT = Path(__file__).resolve().parents[6]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs():
    paths = [HERE / "PROMPT.md", HERE.parent / "FINAL_OPUS55.md"]
    for relative in (
        "reviews/walltime-predictor-training-v1",
        "reviews/heldout-context-ambiguity-v3",
        "low-dma-postreview-v1",
        "native-transfer-postreview-v2",
        "reviews/native-transfer-paper-summary-v1",
        "reviews/native-transfer-figure-v1",
        "quota-pressure-postreview-v1",
    ):
        paths += [
            p
            for p in (STUDY / relative).rglob("*")
            if p.is_file()
            and "__pycache__" not in p.parts
            and p.suffix not in (".pyc", ".log")
            and p.name != "RUNNING.lock"
        ]
    paths += [
        STUDY / "walltime-primary-v3" / name
        for name in (
            "HELDOUT_ERROR.json",
            "HELDOUT_INDEPENDENT_AUDIT.json",
            "MANIFEST.json",
            "PLAN.json",
            "PROTOCOL.json",
            "PROTOCOL_SEAL.json",
        )
    ]
    paths += list((ROOT / "python/moonkvsim/aegiskv/current").glob("*.py"))
    paths += [
        ROOT / "python/moonkvsim/aegiskv" / name
        for name in (
            "evaluation_walltime_predictor.py",
            "evaluation_native_transfer.py",
            "evaluation_quota.py",
        )
    ]
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(set(paths))}


def main():
    assert (STUDY / "quota-pressure-postreview-v1/FINAL_AUDIT.json").is_file()
    output = HERE / "INVOCATION.json"
    if output.exists():
        raise RuntimeError("review already launched; do not overwrite its record")
    before = inputs()
    record = dict(
        started_utc=datetime.now(UTC).isoformat(),
        input_sha256=before,
        requested_model="claude-opus-5-5-max",
        scope="completed remediation methods only",
    )
    output.write_text(json.dumps(record, indent=2) + "\n")
    binary = "/home/comp/zhanzhao/.local/share/cursor-agent/proxy-bin/cursor-agent"
    with (HERE / "review.jsonl").open("w") as stdout, (HERE / "review.stderr").open("w") as stderr:
        result = subprocess.run(
            [
                binary,
                "--model",
                record["requested_model"],
                "--mode",
                "ask",
                "--print",
                "--output-format",
                "stream-json",
                "--trust",
                (HERE / "PROMPT.md").read_text(),
            ],
            cwd=ROOT,
            stdout=stdout,
            stderr=stderr,
        )
    after = inputs()
    record.update(
        finished_utc=datetime.now(UTC).isoformat(),
        exit_code=result.returncode,
        input_drift=[k for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)],
        after_sha256=after,
    )
    for line in (HERE / "review.jsonl").read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            record["reported_model"] = event.get("model")
            record["review_session_id"] = event.get("session_id")
        if event.get("type") == "result" and isinstance(event.get("result"), str):
            (HERE / "REVIEW.md").write_text(event["result"] + "\n")
            record["review_result_subtype"] = event.get("subtype")
            record["review_is_error"] = event.get("is_error")
    output.write_text(json.dumps(record, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: record.get(k)
                for k in (
                    "exit_code",
                    "reported_model",
                    "review_session_id",
                    "input_drift",
                )
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
