"""Finalize the complete campaign without re-exporting its frozen figures."""

import csv
import gzip
import hashlib
import json
import runpy
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent
ROOT = SOURCE.parents[4]
FIGURES = SOURCE / "figures"


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main():
    validation = read(SOURCE / "VALIDATION.json")
    assert validation["all_passed"] and validation["runs"] == 143 and validation["pairs"] == 94
    assert len(read(SOURCE / "RUNS.json")) == 143
    assert (SOURCE / "README.md").exists()
    subprocess.run([sys.executable, str(SOURCE / "audit_result_details.py")], check=True)
    audit = read(SOURCE / "TRACE_MECHANISM_AUDIT.json")
    assert audit["all_passed"] and audit["runs_audited"] == 143
    metadata = read(FIGURES / "EXPORT_METADATA.json")
    plot = SOURCE / "reports/reviewed_plot_structural_campaign.py"
    assert sha(plot) == metadata["script_sha256"], "reviewed plotting source changed"
    figure_data_sha = sha(FIGURES / "figure-data.csv")
    headline_sha = sha(FIGURES / "headline-results.csv")
    frozen = {
        f"{row['name']}.{extension}": sha(FIGURES / f"{row['name']}.{extension}")
        for row in metadata["exports"]
        for extension in ("pdf", "png", "svg")
    }
    code = runpy.run_path(str(plot), run_name="structural_figure_table_finalizer")
    # The reviewed original is preserved byte-for-byte outside its original
    # directory. Only bind its data locations; keep all table/figure code exact.
    code["verify_inputs"].__globals__.update(SOURCE=SOURCE, OUT=FIGURES)
    values = code["verify_inputs"](False)
    code["tables"](*values, main_only=False)
    assert sha(FIGURES / "figure-data.csv") == figure_data_sha
    assert sha(FIGURES / "headline-results.csv") == headline_sha
    assert all(sha(FIGURES / name) == digest for name, digest in frozen.items())
    erratum = read(SOURCE / "RECOVERY_DOMAIN_ERRATUM.json")
    assert erratum["corrected_semantics_evidence"] is False
    version_note = (
        "These results describe the original frozen runtime. The subsequently "
        "diagnosed recovery-selector domain issue can affect dense overlap fractions "
        "and sparse selected block identities; numerical recovery/WCT effects have "
        "not been measured by corrected runs. Completion, ledger and EOS checks "
        "establish historical-model accounting only, not repaired semantics. "
        "See RECOVERY_DOMAIN_ERRATUM.md at the campaign root."
    )
    for path in (SOURCE / "README.md", FIGURES / "RESULTS.md"):
        with path.open("a") as stream:
            stream.write("\n" + version_note + "\n")
    with (FIGURES / "scale-resource-results.csv").open() as stream:
        scale = list(csv.DictReader(stream))
    plan, host = read(SOURCE / "PLAN.json"), read(SOURCE / "reports/SCALE_HOST_METADATA.json")
    ranges = []
    for count in (8, 32, 128):
        rows = [row for row in scale if int(row["workflows"]) == count]
        assert len(rows) == 4
        workload = plan["workloads"][f"history_reuse-n{count}-s7"]
        agents = json.loads(gzip.decompress((SOURCE / workload["path"]).read_bytes()))
        ranges.append(
            dict(
                workflows=count,
                agents=len(agents),
                invocations=sum(len(a["calls"]) for a in agents),
                cells=4,
                wall_min_s=min(float(r["run_wall_seconds"]) for r in rows),
                wall_max_s=max(float(r["run_wall_seconds"]) for r in rows),
                cpu_min_s=min(float(r["process_cpu_seconds"]) for r in rows),
                cpu_max_s=max(float(r["process_cpu_seconds"]) for r in rows),
                worker_peak_rss_min_MiB=min(
                    int(r["worker_lifetime_peak_rss_kib"]) / 1024 for r in rows
                ),
                worker_peak_rss_max_MiB=max(
                    int(r["worker_lifetime_peak_rss_kib"]) / 1024 for r in rows
                ),
            )
        )
    addition = [
        "",
        "## Host and interpretation",
        "",
        f"CPU: {host['cpu_model']}; {host['host_logical_cpus']} host logical CPUs, {host['process_affinity_logical_cpus']} allowed by process affinity. Host MemTotal: {host['host_memory_total_bytes']:,} B ({host['host_memory_total_bytes'] / 2**40:.6f} TiB). Python: {host['python_version']}. Exact capture time and point-in-time load are in reports/SCALE_HOST_METADATA.json.",
        "",
        "Concurrent campaigns shared this host. Each cell ran once; there are no timing repetitions or confidence intervals. These are simulator execution-scale measurements, not production-controller scalability, controller-only overhead, or GPU serving throughput. Worker-lifetime RSS includes earlier cases and cached inputs.",
        "",
        version_note,
        "",
        "| Workflows / Agents / invocations | CPU range over four distinct cases (s) | Wall range (s) | Worker-lifetime RSS range (MiB) |",
        "|---|---:|---:|---:|",
    ]
    for row in ranges:
        addition.append(
            f"| {row['workflows']} / {row['agents']} / {row['invocations']} | {row['cpu_min_s']:.6f} to {row['cpu_max_s']:.6f} | {row['wall_min_s']:.6f} to {row['wall_max_s']:.6f} | {row['worker_peak_rss_min_MiB']:.6f} to {row['worker_peak_rss_max_MiB']:.6f} |"
        )
    with (FIGURES / "SCALE_RESOURCES.md").open("a") as stream:
        stream.write("\n".join(addition) + "\n")
    write(
        FIGURES / "SCALE_RANGES.json",
        dict(
            rows=ranges,
            source_csv_sha256=sha(FIGURES / "scale-resource-results.csv"),
            host_metadata_sha256=sha(SOURCE / "reports/SCALE_HOST_METADATA.json"),
        ),
    )
    metadata["entire_campaign_status"] = "COMPLETE"
    metadata["corrected_semantics_evidence"] = False
    metadata["recovery_domain_erratum_sha256"] = sha(SOURCE / "RECOVERY_DOMAIN_ERRATUM.json")
    metadata["full_campaign_audit"] = {
        "runs": 143,
        "pairs": 94,
        "workflow_pairs": 1040,
        "source_sha256": sha(SOURCE / "TRACE_MECHANISM_AUDIT.json"),
    }
    metadata["tables_inputs"] = {
        name: sha(SOURCE / name)
        for name in (
            "paired-workflows.csv",
            "recovery-events.csv",
            "VALIDATION.json",
            "raw-runs.csv",
        )
    }
    metadata["finalization"] = (
        "Tables and audit scope finalized; reviewed main-figure PDF/PNG/SVG bytes unchanged."
    )
    write(FIGURES / "EXPORT_METADATA.json", metadata)
    review = read(FIGURES / "FIGURE_REVIEW.json")
    review["scope"] = (
        "143/143 whole campaign audited; both figures still use exactly the same 135 main runs"
    )
    review["export_metadata_sha256"] = sha(FIGURES / "EXPORT_METADATA.json")
    review["all_frozen_figure_bytes_unchanged_at_finalization"] = True
    review["corrected_semantics_evidence"] = False
    review["known_semantic_limit"] = version_note
    write(FIGURES / "FIGURE_REVIEW.json", review)
    results = dict(
        passed=True,
        audit_scope="Historical frozen model: source/input binding, completion, event and resource accounting. Not recovery-domain conformance of a corrected implementation.",
        corrected_semantics_evidence=False,
        runs=143,
        failure_pairs=94,
        paired_workflows=1040,
        protected_recovery_eos_checks=len(audit["eos_full_restore_exposure_checks"]),
        eos_before_full_restore_count=audit["eos_before_full_restore_count"],
        recovery_events=audit["recovery_event_count"],
        source_snapshot_preserved=True,
        all_frozen_main_figure_bytes_unchanged=True,
        frozen_figure_hashes=frozen,
        scale_ranges=ranges,
        finalizer_sha256=sha(Path(__file__)),
        output_sha256={
            str(p.relative_to(SOURCE)): sha(p)
            for p in (
                SOURCE / "TRACE_MECHANISM_AUDIT.json",
                SOURCE / "PHASE_AUDIT.json",
                SOURCE / "RECOVERY_DOMAIN_ERRATUM.json",
                SOURCE / "RECOVERY_DOMAIN_ERRATUM.md",
                FIGURES / "scale-resource-results.csv",
                FIGURES / "SCALE_RESOURCES.md",
                FIGURES / "SCALE_RANGES.json",
                FIGURES / "RESULTS.md",
                FIGURES / "EXPORT_METADATA.json",
                FIGURES / "FIGURE_REVIEW.json",
            )
        },
    )
    write(SOURCE / "FINAL_AUDIT.json", results)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
