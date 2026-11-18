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
        HERE / "final-review-prompt.txt",
        STUDY / "PROTOCOL.md",
        STUDY / "LITERATURE_AND_DESIGN.md",
        ROOT / "benchmark/AegisKV/docs/DESIGN_IMPLEMENTATION_COVERAGE.md",
        ROOT / "benchmark/AegisKV/docs/current-design-simulation.md",
        HERE / "REVIEW_DISPOSITION.md",
        HERE / "PROPOSED_CLAIM_CORRECTIONS.md",
    ]
    for campaign in (
        "formal-core-v2-corrected",
        "structural-campaign-v2-main",
        "sensitivity-campaign-v2-corrected",
        "capacity-slack-ablation-v2-corrected",
        "native-topk-warm",
        "slack-mechanism-posthoc-v2-corrected",
    ):
        for name in (
            "AUDIT.json",
            "PLAN.json",
            "MANIFEST.json",
            "STATISTICS.json",
            "RESULTS.md",
            "TIMING_METADATA_ERRATUM.json",
            "INDEPENDENT_AUDIT.json",
            "PAPER_NUMBERS_V2.md",
            "PAIRED_RESULTS.json",
            "REPLAY_MANIFEST.json",
            "REPLAY_RESULT.json",
            "REPLAY_IMPORTS.json",
            "INTERRUPTION_RECOVERY.json",
        ):
            path = STUDY / campaign / name
            if path.exists():
                paths.append(path)
        paths += list((STUDY / campaign).glob("*AUDIT*.json"))
        paths += list((STUDY / campaign).glob("*MATCH*.json"))
        for subdirectory in ("endpoints", "figures", "reports"):
            for extension in ("*.json", "*.csv", "*.md", "*.pdf", "*.py"):
                paths += list((STUDY / campaign / subdirectory).glob(extension))
    paths += list((ROOT / "python/moonkvsim/aegiskv/current").glob("*.py"))
    paths += list((STUDY / "structural-campaign-v1/reports").glob("*SCALE*"))
    paths += list((STUDY / "structural-campaign-v1").glob("*scale*.csv"))
    paths += [
        path
        for path in (
            HERE / "CANDIDATE_OPUS55.md",
            HERE / "CANDIDATE_REVIEW_INVOCATION.json",
            HERE / "PRIMARY_EOS_BOUNDARY_CHECK.json",
            HERE / "STRUCTURAL_EOS_BOUNDARY_CHECK.json",
            HERE / "POSTHOC_SLACK_INDEPENDENT_REVIEW.json",
            HERE / "POSTHOC_SLACK_V2_INDEPENDENT_REVIEW.json",
            HERE / "PAPER_NUMBERS_V2.md",
            HERE / "PAPER_NUMBERS_V2.json",
            HERE / "PRIMARY_V2_FINAL_INDEPENDENT_REVIEW.md",
            HERE / "PRIMARY_V2_FINAL_INDEPENDENT_REVIEW.json",
            HERE / "AUXILIARY_O1_V2_FINAL_SEAL.json",
            HERE / "TIMING_METADATA_REVIEW.md",
            HERE / "DESIGN_CONFORMANCE_SPOTCHECK.md",
            HERE / "CAUSAL_DOMAIN_APPLICATION.json",
            HERE / "QUEUED_HISTORY_APPLICATION.json",
            HERE / "PROSPECTIVE_METADATA_APPLICATION.json",
            HERE / "FINAL_PACKAGE_READY.json",
            STUDY / "paper-preview/EXPORT_REVIEW.json",
            STUDY / "paper-preview/VISUAL_REVIEW.json",
            STUDY / "slack-mechanism-posthoc-v2-corrected/NONEMPTY_OBSERVATION_TRANSPARENCY.json",
        )
        if path.exists()
    ]
    for subdirectory in (
        "native-topk-operating-point",
        "v1-v2-comparison",
        "o1-dma-corrected-v2-audit",
        "coprimary-v2-crosscheck",
    ):
        for extension in ("*.json", "*.csv", "*.md", "*.tex"):
            paths += list((HERE / subdirectory).glob(extension))
    paths += list((STUDY / "paper-preview").glob("page-*.png"))
    paths = [path for path in paths if path.is_file()]
    return {str(path.relative_to(ROOT)): sha(path) for path in sorted(set(paths))}


if __name__ == "__main__":
    binary = "/home/comp/zhanzhao/.local/share/cursor-agent/proxy-bin/cursor-agent"
    readiness = json.loads((HERE / "FINAL_PACKAGE_READY.json").read_text())
    assert readiness["status"] == "READY_FOR_REVIEW"
    assert readiness["paper_tex_sha256"] == sha(PAPER / "evaluation.tex")
    assert readiness["paper_pdf_sha256"] == sha(PAPER / "main.pdf")
    for campaign, expected in {
        "formal-core-v2-corrected": 180,
        "structural-campaign-v2-main": 135,
        "sensitivity-campaign-v2-corrected": 126,
        "capacity-slack-ablation-v2-corrected": 32,
        "slack-mechanism-posthoc-v2-corrected": 10,
    }.items():
        assert len(list((STUDY / campaign / "runs").glob("*/COMPLETE.json"))) == expected
    before = inputs()
    record = dict(
        started_utc=datetime.datetime.now(datetime.UTC).isoformat(),
        requested_model="claude-opus-5-5-max",
        binary=binary,
        input_sha256=before,
    )
    candidate = json.loads((HERE / "CANDIDATE_REVIEW_INVOCATION.json").read_text())
    if candidate.get("exit_code") != 0 or not candidate.get("review_session_id"):
        raise RuntimeError("completed candidate review is required before final continuation")
    record["resumed_candidate_session"] = candidate["review_session_id"]
    (HERE / "FINAL_REVIEW_INVOCATION.json").write_text(json.dumps(record, indent=2) + "\n")
    prompt = (HERE / "final-review-prompt.txt").read_text()
    with (
        (HERE / "final-opus55.jsonl").open("w") as stdout,
        (HERE / "final-opus55.stderr").open("w") as stderr,
    ):
        result = subprocess.run(
            [
                binary,
                "--model",
                "claude-opus-5-5-max",
                "--resume",
                record["resumed_candidate_session"],
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
    (HERE / "FINAL_REVIEW_INVOCATION.json").write_text(json.dumps(record, indent=2) + "\n")
    (HERE / "final-exit.txt").write_text(str(result.returncode) + "\n")
    for line in (HERE / "final-opus55.jsonl").read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            record["reported_model"] = event.get("model")
            record["review_session_id"] = event.get("session_id")
        if event.get("type") == "result" and isinstance(event.get("result"), str):
            (HERE / "FINAL_OPUS55.md").write_text(event["result"] + "\n")
            record["review_result_subtype"] = event.get("subtype")
            record["review_is_error"] = event.get("is_error")
    (HERE / "FINAL_REVIEW_INVOCATION.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({key: record[key] for key in ("finished_utc", "exit_code", "input_drift")}))
