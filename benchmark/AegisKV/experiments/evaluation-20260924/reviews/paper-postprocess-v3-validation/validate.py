"""Read sealed v2 artifacts to check v3 postprocessor arithmetic; no DES."""

import csv
import hashlib
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
BASE = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924"
SOURCE = ROOT / "benchmark/AegisKV/experiments/scripts/current_design/finalize_walltime_primary.py"
OLD = BASE / "formal-core-v2-corrected"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    return list(csv.DictReader(path.open()))


spec = importlib.util.spec_from_file_location("paper_postprocess", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.completed_gate(BASE / "walltime-primary-v3") is False
assert json.loads((OLD / "AUDIT.json").read_text())["status"] == "PASS"
reference = BASE / "reviews/coprimary-v2-crosscheck/agent-latency-six-rows.csv"
with tempfile.TemporaryDirectory(prefix="aegiskv-paper-arithmetic-") as directory:
    out = Path(directory)
    for name in ("PLAN.json", "endpoints", "runs"):
        (out / name).symlink_to(OLD / name)
    target = out / "paper-summary"
    target.mkdir()
    # The temporary fixture has old v2 data, not a v3 deployment. Only bypass
    # its v3-specific completion gate here; never write v3 outputs or audit PASS.
    module.completed_gate = lambda _: True
    module.paper_data(out)
    for actual, expected in zip(rows(target / "agent-latency.csv"), rows(reference), strict=True):
        assert (actual["model"], actual["nominal_load"]) == (
            expected["model"], expected["nominal_load"]
        )
        for a, b in (
            ("restart_seconds", "restart_mean_failure_to_first_new_s"),
            ("dram_seconds", "dram_mean_failure_to_first_new_s"),
            ("hbm_gain_ms", "hbm_gain_dram_minus_aegis_ms"),
        ):
            assert actual[a] == expected[b]
    static = json.loads((target / "STATIC_AEGIS_COMPARISON.json").read_text())
    assert static["equal_wct_pairs"] == 2232
    identity = rows(target / "policy-comparisons-per-identity.csv")
    adverse = next(r for r in identity if (
        r["model"], r["nominal_load"], r["fault_index"], r["baseline"], r["method"]
    ) == ("Qwen3-8B", "0.9", "1", "dram", "aegiskv"))
    assert int(adverse["target_wct_gain_ns"]) == 1099886
    assert int(adverse["cohort_sum_wct_gain_ns"]) == -3402435834
    workflow = rows(target / "paired-workflows.csv")
    canceling = [int(r["gain_ns"]) for r in workflow if (
        r["model"], r["nominal_load"], r["fault_index"], r["baseline"], r["method"]
    ) == ("Qwen3-32B", "0.9", "4", "all_dram", "dram") and int(r["gain_ns"])]
    assert sorted(canceling) == [-4113432720, 4113432720], canceling
    (out / "workloads").symlink_to(OLD / "workloads")
    (out / "PROTOCOL.json").write_text(json.dumps({"original_campaign": str(OLD)}))
    (out / "INPUT_MATCH.json").write_text("{}")
    (out / "postprocess_source_snapshot").mkdir()
    fallback_helper = SOURCE.with_name("audit_o1_dma_evidence.py")
    fallback_reference = BASE / "reviews/o1-dma-corrected-v2-audit/AUDIT.json"
    shutil.copyfile(fallback_helper, out / "postprocess_source_snapshot/audit_o1_dma_evidence.py")
    module.bindings = lambda _: dict(fixture="old-old arithmetic only")
    module.compare_versions(out)
    comparison = json.loads((target / "V2_V3_COMPARISON.json").read_text())
    assert comparison["changed_workflow_wct_pairs"] == comparison["changed_target_delta"] == 0
    assert comparison["changed_agent_latency"] == comparison["changed_saved_request_workers"] == 0
    module.fallback_windows(out)
    fallback = json.loads((target / "FALLBACK_CONTROL_WINDOWS.json").read_text())
    assert fallback["runs"] == json.loads(fallback_reference.read_text())["detailed_fallback"]
    module.append_summary(out)
    assert len(rows(target / "v2-v3-cell-summary.csv")) == 30
    assert len(rows(target / "v2-v3-policy-contrasts.csv")) == 120
    result = dict(
        status="PASS", no_DES=True,
        scope="Old sealed v2 arithmetic fixture only; not a v3 numerical result",
        v3_gate_at_check=False,
        checks=["six latency rows exact numeric strings", "2232 Static equal WCT pairs",
                "target/cohort adverse sign reversal exact ns", "canceling AllDRAM pair exact ns",
                "old-old version comparison exact zero across180/11160/150",
                "same helper exactly reproduces old two-run fallback denominator/reasons/Slack"],
        row_counts={p.name: len(rows(p)) for p in target.glob("*.csv")},
        source_sha256={str(p): sha(p) for p in [
            Path(__file__), SOURCE, reference, fallback_helper, fallback_reference,
            OLD / "AUDIT.json", OLD / "PLAN.json",
            OLD / "endpoints/PROVENANCE.json", *sorted((OLD / "runs").glob("*/summary.json")),
            *sorted((OLD / "endpoints").glob("*.csv")),
        ]},
    )
(Path(__file__).parent / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
print("PASS: six rows,2232Static,7440WF,180 version comparison and two fallback reconstructions")
