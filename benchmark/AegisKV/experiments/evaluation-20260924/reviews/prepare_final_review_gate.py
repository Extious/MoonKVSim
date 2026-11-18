"""Bind the completed corrected package after independent and visual review."""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
PAPER = ROOT / "benchmark/AegisKV/paper"
VERSION = (
    "checkpoint-decay-hysteresis-incremental-g-20260924-eosfix1-causal-domain1-queued-history1"
)
RUNTIME_SHA = "de3a9ce7791218a74e8d50651c2ba1249b194e500eabc0fd9a91c52b978b8c5f"
CAMPAIGNS = {
    "formal-core-v2-corrected": (180, "AUDIT.json", "passed"),
    "structural-campaign-v2-main": (135, "TRACE_MECHANISM_AUDIT.json", "all_passed"),
    "sensitivity-campaign-v2-corrected": (126, "AUDIT.json", "complete"),
    "capacity-slack-ablation-v2-corrected": (32, "INDEPENDENT_VARIANT_AUDIT.json", "passed"),
    "slack-mechanism-posthoc-v2-corrected": (10, "AUDIT.json", "passed"),
}
FIGURES = {
    "eval-primary-wct.pdf": "formal-core-v2-corrected/endpoints/figures/primary-target-wct.pdf",
    "eval-structural-wct.pdf": "structural-campaign-v2-main/figures/structural-target-wct.pdf",
    "eval-resource-sensitivity.pdf": (
        "sensitivity-campaign-v2-corrected/figures/sensitivity-resources.pdf"
    ),
    "eval-native-topk.pdf": "native-topk-warm/figures/native-topk-warm-coverage.pdf",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    assert sha(ROOT / "python/moonkvsim/aegiskv/current/runtime.py") == RUNTIME_SHA
    resume_path = STUDY / "formal-core-v2-corrected/INTERRUPTION_RECOVERY.json"
    resume = read(resume_path)
    assert resume["status"] == "COMPLETE"
    assert resume["all_previous_markers_and_summaries_unchanged"] is True
    assert resume["imported_sources_verified"] is True
    results = {}
    for name, (count, audit_name, passed_key) in CAMPAIGNS.items():
        campaign = STUDY / name
        audit_path = campaign / audit_name
        assert read(audit_path)[passed_key] is True, name
        markers = sorted((campaign / "runs").glob("*/COMPLETE.json"))
        assert len(markers) == count, (name, len(markers), count)
        summaries = {}
        for marker in markers:
            summary_path = marker.parent / "summary.json"
            record, summary = read(marker), read(summary_path)
            if "summary_sha256" in record:
                expected_summary = record["summary_sha256"]
            elif "artifact_sha256" in record:
                expected_summary = record["artifact_sha256"]["summary.json"]
            else:
                expected_summary = record["artifacts_sha256"]["summary.json"]
            assert expected_summary == sha(summary_path), marker
            assert summary["design_version"] == VERSION, summary_path
            assert summary["oracle_reservation_count"] == 0, summary_path
            assert summary["duration_profile"] == "GridDurationProfile", summary_path
            assert all(
                summary[k] is True
                for k in ("complete", "output_tokens_exact", "terminal_allocations_zero")
            ), summary_path
            summaries[marker.parent.name] = sha(summary_path)
        snapshot_runtime = campaign / "source_snapshot/python/moonkvsim/aegiskv/current/runtime.py"
        assert sha(snapshot_runtime) == RUNTIME_SHA
        results[name] = dict(
            completed=count,
            audit=str(audit_path.relative_to(ROOT)),
            audit_sha256=sha(audit_path),
            manifest_sha256=sha(campaign / "MANIFEST.json"),
            plan_sha256=sha(campaign / "PLAN.json"),
            runtime_sha256=sha(snapshot_runtime),
            summary_sha256=summaries,
        )
    figures = {}
    for dest, source in FIGURES.items():
        assert sha(PAPER / "figures" / dest) == sha(STUDY / source), dest
        figures[dest] = dict(source=source, sha256=sha(STUDY / source))
    export = read(STUDY / "paper-preview/EXPORT_REVIEW.json")
    visual = read(STUDY / "paper-preview/VISUAL_REVIEW.json")
    assert export["manuscript_sha256"] == sha(PAPER / "main.pdf")
    assert export["tex_sha256"] == sha(PAPER / "evaluation.tex")
    assert visual["status"] == "PASS"
    assert visual["manuscript_sha256"] == export["manuscript_sha256"]
    assert visual["tex_sha256"] == export["tex_sha256"]
    assert sorted(visual["color_pages_checked"]) == sorted(export["rendered_pages"])
    assert sorted(visual["grayscale_pages_checked"]) == sorted(export["rendered_pages"])
    report = dict(
        status="READY_FOR_REVIEW",
        meaning="Completion, provenance, and render review gate; not publication approval",
        created_utc=datetime.datetime.now(datetime.UTC).isoformat(),
        design_version=VERSION,
        current_completed_conditions=sum(v["completed"] for v in results.values()),
        reruns_are_additional_statistical_samples=False,
        paper_tex_sha256=export["tex_sha256"],
        paper_pdf_sha256=export["manuscript_sha256"],
        source_preservation=export["source_preservation"],
        page_count=export["page_count"],
        evaluation_page_range=export["evaluation_page_range"],
        campaign_results=results,
        figure_sources=figures,
        visual_review_sha256=sha(STUDY / "paper-preview/VISUAL_REVIEW.json"),
        gate_script_sha256=sha(Path(__file__)),
        interruption_recovery_sha256=sha(resume_path),
    )
    (HERE / "FINAL_PACKAGE_READY.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "current_completed_conditions",
                    "paper_tex_sha256",
                    "paper_pdf_sha256",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
