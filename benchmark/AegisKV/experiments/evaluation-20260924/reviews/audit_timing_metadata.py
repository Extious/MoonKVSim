#!/usr/bin/env python3
"""Append timing-metadata errata; leave original campaign seals/results intact."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CAMPAIGNS = {
    "sensitivity-campaign-v1": ["run_sensitivity_campaign.py"],
    "capacity-slack-ablation-v1": ["run_capacity_slack_ablation.py", "run_sensitivity_campaign.py"],
    "slack-mechanism-posthoc-v1": ["run_slack_mechanism_diagnostic.py"],
}
RUNNER_DIRECTORY = "benchmark/AegisKV/experiments/scripts/current_design/"
MODULES = [
    "python/moonkvsim/aegiskv/current/__main__.py",
    "python/moonkvsim/aegiskv/current/runtime.py",
    "python/moonkvsim/aegiskv/evaluation_profile.py",
]
OLD_TEXT = "configured linear compute and shared weighted max-min fair byte flows"
CORRECTION = (
    "Qwen3-8B TP1 GridDurationProfile using pinned AIConfigurator HYBRID operator "
    "estimates, bounded prefix/extend interpolation and per-token decode summation; "
    "shared weighted max-min fair byte-flow DES. Not end-to-end calibrated; "
    "configured compute-DMA slowdown applies separately when nonzero."
)


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def numbered_matches(path, terms):
    return [
        dict(line=i, text=line.strip())
        for i, line in enumerate(path.read_text().splitlines(), 1)
        if any(term in line for term in terms)
    ]


def main():
    now = datetime.now(UTC).isoformat()
    reports = []
    for campaign, runners in CAMPAIGNS.items():
        root = BASE / campaign
        for name in ("TIMING_METADATA_ERRATUM.json", "TIMING_METADATA_ERRATUM.md"):
            if (root / name).exists():
                raise FileExistsError(f"Preserve the existing appended erratum: {root / name}")
        manifest, plan = read(root / "MANIFEST.json"), read(root / "PLAN.json")
        assert manifest["timing"] == OLD_TEXT
        original_hashes = {}

        def seal(path, root=root, original_hashes=original_hashes):
            key = str(path.relative_to(root))
            original_hashes[key] = digest(path)
            return original_hashes[key]

        for name in ("MANIFEST.json", "PLAN.json", "AUDIT.json"):
            seal(root / name)
        for name, expected in manifest.get("control_sha256", {}).items():
            assert seal(root / name) == expected
        if (root / "SEAL.json").exists():
            seal(root / "SEAL.json")
            for name, expected in read(root / "SEAL.json").items():
                assert seal(root / name) == expected
        profile_path = root / plan["profile"]
        profile_hash = seal(profile_path)
        assert profile_hash == manifest.get("profile_sha256", plan.get("profile_sha256"))
        profile = read(profile_path)
        assert profile["schema"] == "aegiskv.duration-grid.v1"
        assert profile["model"] == "Qwen/Qwen3-8B" and profile["tp"] == 1
        assert profile["database_mode"] == "HYBRID"
        assert profile["physical_execution"] is False and profile["calibrated"] is False
        code_evidence = []
        for relative in [*MODULES, *[RUNNER_DIRECTORY + name for name in runners]]:
            path = root / "source_snapshot" / relative
            assert seal(path) == manifest["source_sha256"][relative]
            code_evidence.append(
                dict(
                    path=str(path.relative_to(root)),
                    sha256=digest(path),
                    relevant_lines=numbered_matches(
                        path,
                        [
                            '"timing":',
                            "GridDurationProfile(",
                            "duration_profile=",
                            "self.duration_profile is None",
                            "self.duration_profile(self.config",
                            "shared.run(",
                            "runtime = ObservedRuntime(",
                            "class GridDurationProfile",
                            'getattr(self.duration_profile, "name"',
                        ],
                    ),
                )
            )
        summary_evidence, slowdowns, fallback_config = [], set(), set()
        for job in plan["jobs"]:
            folder = root / "runs" / job["id"]
            marker = read(folder / "COMPLETE.json")
            summary, config = read(folder / "summary.json"), read(folder / "config.json")
            artifacts = marker.get("artifact_sha256", marker.get("artifacts_sha256"))
            assert marker["profile_sha256"] == profile_hash
            assert summary["duration_profile"] == "GridDurationProfile"
            assert summary["complete"] and summary["terminal_allocations_zero"]
            assert config == job["config"]
            marker_hash = seal(folder / "COMPLETE.json")
            for name in ("summary.json", "config.json"):
                assert seal(folder / name) == artifacts[name]
            assert summary["config_sha256"] == digest(folder / "config.json")
            slowdowns.add(config["compute_dma_slowdown"])
            fallback_config.add((config["prefill_ns_per_token"], config["decode_ns_per_token"]))
            summary_evidence.append(
                dict(
                    id=job["id"],
                    summary_sha256=digest(folder / "summary.json"),
                    config_sha256=digest(folder / "config.json"),
                    COMPLETE_sha256=marker_hash,
                    profile_sha256=marker["profile_sha256"],
                    duration_profile=summary["duration_profile"],
                    compute_dma_slowdown=config["compute_dma_slowdown"],
                    dma_compute_interference_model=summary["dma_compute_interference_model"],
                )
            )
        assert (
            len(summary_evidence)
            == {
                "sensitivity-campaign-v1": 126,
                "capacity-slack-ablation-v1": 32,
                "slack-mechanism-posthoc-v1": 10,
            }[campaign]
        )
        result_files = list(root.glob("*.csv"))
        if (root / "PAIRED_RESULTS.json").exists():
            result_files.append(root / "PAIRED_RESULTS.json")
        if (root / "figures/PROVENANCE.json").exists():
            result_files.append(root / "figures/PROVENANCE.json")
        if (root / "figures").exists():
            result_files.extend(
                p
                for p in (root / "figures").iterdir()
                if p.suffix in {".pdf", ".png", ".svg", ".csv"}
            )
        for path in result_files:
            seal(path)
        notes = [
            "The word 'linear' in bounded grid interpolation does not mean "
            "the unused constant-ns/token fallback.",
            "Summary class names are not the only evidence: sealed runner construction, "
            "call forwarding, runtime branch, profile and COMPLETE hashes agree.",
            "This correction changes no profile values, simulated schedules, outputs, "
            "aggregate results, calibration status or scientific outcome.",
            "No simulator run was launched; no original seal, manifest, audit, "
            "plot or source was rewritten.",
        ]
        related = dict(
            original_field="MANIFEST.foreground_dma_compute_interference",
            original_value=manifest["foreground_dma_compute_interference"],
            actual_configured_values=sorted(slowdowns),
            interpretation=(
                "Nonzero values are event-start sensitivity assumptions, "
                "not calibrated GPU/DMA interference."
            ),
            incorrect_for_nonzero_conditions=any(slowdowns),
        )
        report = dict(
            schema="aegiskv.timing-metadata-erratum.v1",
            campaign=campaign,
            reviewed_utc=now,
            status="VERIFIED_METADATA_ERRATUM",
            original_field="MANIFEST.timing",
            original_value=OLD_TEXT,
            corrected_interpretation=CORRECTION,
            cause=(
                "Generic current.__main__.manifest() description inherited without a "
                "campaign-specific timing override; the runner passed the grid regardless."
            ),
            original_manifest_sha256=digest(root / "MANIFEST.json"),
            profile_path=plan["profile"],
            profile_sha256=profile_hash,
            profile_metadata={
                k: profile[k]
                for k in [
                    "model",
                    "revision",
                    "tp",
                    "hardware",
                    "batch_size",
                    "backend",
                    "backend_version",
                    "database_mode",
                    "timing_evidence",
                    "calibrated",
                    "physical_execution",
                    "interpolation",
                    "native_max_context",
                    "max_profile_context",
                    "extended_context",
                ]
            },
            frozen_code_evidence=code_evidence,
            verified_runs=len(summary_evidence),
            run_summary_evidence=summary_evidence,
            configured_linear_fallback_values=[
                dict(prefill_ns_per_token=a, decode_ns_per_token=b)
                for a, b in sorted(fallback_config)
            ],
            fallback_used=False,
            related_compute_DMA_metadata=related,
            original_artifacts_sha256=original_hashes,
            immutable_artifacts_checked=len(original_hashes),
            numeric_results_changed=False,
            original_seals_changed=False,
            simulation_runs_executed=0,
            evidence_limits=notes,
            erratum_script_sha256=digest(Path(__file__)),
        )
        text = f"""# Timing metadata erratum: {campaign}

`MANIFEST.json` retains the generic `timing` value:

> {OLD_TEXT}

The **configured linear compute** wording is incorrect for this campaign.
The frozen runner actually constructs and supplies `GridDurationProfile`.
All **{len(summary_evidence)}** sealed summaries name that provider, and each
COMPLETE marker binds the same profile hash. The runtime's constant
`prefill_ns_per_token` / `decode_ns_per_token` branch applies only when no profile
is supplied; its presence in the saved config does not make it the active model.

The correct interpretation is: **{CORRECTION}**
This is Qwen3-8B TP1, batch-size-one A100 SXM operator estimation with a pinned
vLLM backend database tag. It does not mean vLLM or an A100 was executed here.
Prefix/extend interpolation is linear *within the bounded shape grid*; decode
cost is summed per token. Native context is 40,960; the longer profile grid is
performance-shape evidence only, not model quality or runtime validation.

## Bound evidence

- Original manifest SHA-256: `{digest(root / "MANIFEST.json")}`.
- Profile: `{plan["profile"]}`, SHA-256 `{profile_hash}`.
- Frozen runner(s): {", ".join("`" + name + "`" for name in runners)}.
- The JSON annex records line-numbered frozen runner/provider/runtime evidence,
  all {len(summary_evidence)} summary/config/COMPLETE hashes and the original
  audit, seal, tabular result and plot hashes checked during this review.

Configured DMA slowdown values are `{sorted(slowdowns)}`. The inherited
`foreground_dma_compute_interference` description says
`{manifest["foreground_dma_compute_interference"]}`. Where a nonzero value
exists, that generic omission text is also inaccurate: the saved config and
summary describe the explicit event-start slowdown sensitivity model. It is
still not calibrated interference. The shared max-min byte-flow description
remains valid.

This is an appended metadata correction, **not a rerun**. No original manifest,
seal, audit, source, profile, result or plot was changed. Numerical results are
unchanged; calibration status remains false. Original artifact hashes were
read back after appending this record. The original manifest remains available
so its erroneous field and seal can be independently reproduced.
"""
        # Check originals again immediately before publication; report artifacts
        # are new files and are never substituted into historical seals.
        assert all(digest(root / name) == expected for name, expected in original_hashes.items())
        with (root / "TIMING_METADATA_ERRATUM.json").open("x") as file:
            file.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
        with (root / "TIMING_METADATA_ERRATUM.md").open("x") as file:
            file.write(text)
        assert all(digest(root / name) == expected for name, expected in original_hashes.items())
        reports.append(
            dict(
                campaign=campaign,
                runs=len(summary_evidence),
                profile_sha256=profile_hash,
                erratum_sha256=digest(root / "TIMING_METADATA_ERRATUM.json"),
            )
        )
    index = [
        "# Timing metadata review",
        "",
        "Three campaigns inherited a generic linear-compute manifest description while "
        "their sealed execution used GridDurationProfile. These appended errata preserve "
        "the original seals, sources, profiles, summaries and plots; "
        "no numerical rerun was performed.",
        "",
        "| Campaign | Verified runs | Erratum |",
        "|---|---:|---|",
    ]
    for report in reports:
        name = report["campaign"]
        index.append(
            f"| `{name}` | {report['runs']} | [MD](../{name}/TIMING_METADATA_ERRATUM.md), "
            f"[JSON](../{name}/TIMING_METADATA_ERRATUM.json) |"
        )
    index += [
        "",
        "All three use profile SHA-256 `" + reports[0]["profile_sha256"] + "`. "
        "This pinned AIConfigurator HYBRID table is not end-to-end calibrated. "
        "The provider performs bounded shape-grid interpolation and per-token decode summation; "
        "the generic constant-ns/token fallback was not selected.",
        "",
        "The sensitivity group additionally includes DMA slowdown 0.05 and 0.1, so its inherited "
        "generic interference-omitted description must be read with the actual config and summary. "
        "Capacity and post-hoc groups use slowdown zero.",
        "",
        "`formal-core-v1` and `structural-campaign-v1` already override the manifest timing field "
        "to describe their grid-based timing; no corresponding correction was identified. "
        "Future runner metadata fixes must not rewrite these frozen historical manifests.",
        "",
        "Review script: `audit_timing_metadata.py`. It verified the original manifest/profile, "
        "frozen call chain, all 168 summary/config/COMPLETE records, and original artifacts "
        "before and after publishing only the new errata. The recorded vLLM version is a "
        "profile database/backend tag, not evidence of serving-system execution.",
        "",
    ]
    with (BASE / "reviews/TIMING_METADATA_REVIEW.md").open("x") as file:
        file.write("\n".join(index))
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
