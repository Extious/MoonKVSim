"""Read and bind isolated old/fixed diagnostics; does not execute simulations."""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    source = read(HERE / "PROTOTYPE_SOURCE.json")
    for mode in ("old", "fixed"):
        tree = Path(source[mode])
        for relative, expected in source[f"{mode}_sources"].items():
            assert sha(tree / relative) == expected
        assert sha(tree / "tests/aegiskv/test_recovery_demand_domain.py") == sha(
            HERE / "test_recovery_demand_domain_draft.py"
        )
    for filename, mode, expected_exit in (
        ("OLD_DOMAIN_IMPORTS.json", "old", 1),
        ("OLD_EXISTING_IMPORTS.json", "old", 0),
        ("FIXED_ALL_IMPORTS.json", "fixed", 0),
    ):
        record = read(HERE / filename)
        assert record["exitstatus"] == expected_exit
        for item in record["imports"].values():
            path = Path(item["path"])
            assert path.is_relative_to(Path(source[mode]) / "python")
            assert sha(path) == item["sha256"]
    assert "5 failed, 1 passed" in (HERE / "OLD_DOMAIN_TESTS.log").read_text()
    assert "60 passed" in (HERE / "OLD_EXISTING_TESTS.log").read_text()
    assert "66 passed" in (HERE / "FIXED_ALL_TESTS.log").read_text()
    workflow_rows, layer_rows = [], []
    for attention in ("dense", "synthetic_sparse"):
        results = {}
        for mode in ("old", "fixed"):
            for fault in (0, 1):
                folder = HERE / f"cases-{mode}/workflow-{attention}-F{fault}"
                summary = read(folder / "summary.json")
                assert summary["complete"] and summary["terminal_allocations_zero"]
                assert summary["output_tokens_exact"] and summary["oracle_reservation_count"] == 0
                assert summary["metrics"]["emitted_tokens"] == 8
                results[mode, fault] = summary
        for filename in ("summary.json", "events.json", "flows.json"):
            assert (HERE / f"cases-old/workflow-{attention}-F0" / filename).read_bytes() == (
                HERE / f"cases-fixed/workflow-{attention}-F0" / filename
            ).read_bytes()
        for fault in (0, 1):
            for filename in ("config.json", "failure.json"):
                assert (
                    HERE / f"cases-old/workflow-{attention}-F{fault}" / filename
                ).read_bytes() == (
                    HERE / f"cases-fixed/workflow-{attention}-F{fault}" / filename
                ).read_bytes()
        assert results["old", 1]["failure"] == results["fixed", 1]["failure"]
        for mode in ("old", "fixed"):
            recovery = results[mode, 1]["recoveries"][0]
            assert recovery["checkpoint_tokens"] == 512
            assert recovery["rebuild_tokens"] == 88 and recovery["queue_ns"] == 0
            assert results[mode, 1]["metrics"]["replayed_tokens"] == 88
        old_ns = results["old", 1]["workflows"]["wf"]["wct_ns"]
        fixed_ns = results["fixed", 1]["workflows"]["wf"]["wct_ns"]
        workflow_rows.append(
            dict(
                attention=attention,
                f0_wct_ns=results["old", 0]["workflows"]["wf"]["wct_ns"],
                old_f1_wct_ns=old_ns,
                fixed_f1_wct_ns=fixed_ns,
                fixed_minus_old_ns=fixed_ns - old_ns,
                old_recovery=results["old", 1]["recoveries"][0],
                fixed_recovery=results["fixed", 1]["recoveries"][0],
                old_misses=results["old", 1]["metrics"]["recovery_demand_miss_blocks"],
                fixed_misses=results["fixed", 1]["metrics"]["recovery_demand_miss_blocks"],
            )
        )
        a = read(HERE / f"cases-old/layer-{attention}/result.json")
        b = read(HERE / f"cases-fixed/layer-{attention}/result.json")
        layer_rows.append(
            dict(
                attention=attention,
                old=a,
                fixed=b,
                fixed_minus_old_layer_finish_ns=b["layer_finish_ns"] - a["layer_finish_ns"],
                drain_field_note=(
                    "full_restore_or_drain_ns is DES final event time, not restore_done_ns"
                ),
            )
        )
    result = dict(
        status="PASS_ISOLATED_PROTOTYPE",
        live_source_modified=False,
        source_manifest_sha256=sha(HERE / "PROTOTYPE_SOURCE.json"),
        runtime_old_sha256=source["old_sources"]["python/moonkvsim/aegiskv/current/runtime.py"],
        runtime_fixed_sha256=source["fixed_sources"]["python/moonkvsim/aegiskv/current/runtime.py"],
        old_domain_tests=dict(failed=5, passed=1),
        old_existing_tests=dict(passed=60),
        fixed_domain_and_existing_tests=dict(passed=66),
        simulations=dict(workflow_runs=8, initialized_layer_runs=4, campaign_runs=0),
        interpretation=(
            "Fixed linear-cost low-H2D diagnostics; "
            "not native, calibrated or campaign effect sizes."
        ),
        workflow_comparisons=workflow_rows,
        layer_comparisons=layer_rows,
        artifact_sha256={
            str(p.relative_to(HERE)): sha(p)
            for p in sorted(HERE.rglob("*"))
            if p.is_file()
            and p.name != "PROTOTYPE_VALIDATION.json"
            and "__pycache__" not in p.parts
        },
    )
    (HERE / "PROTOTYPE_VALIDATION.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in ("status", "runtime_old_sha256", "runtime_fixed_sha256", "simulations")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
