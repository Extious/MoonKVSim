from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from moonkvsim.common.hash import sha256_json

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "benchmark/AegisKV/experiments/results/figures/generate_aegiskv_paper_sweeps.py"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_test_paper_sweep_figures", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    matplotlib = ModuleType("matplotlib")
    pyplot = ModuleType("matplotlib.pyplot")
    numpy = ModuleType("numpy")
    saved = {name: sys.modules.get(name) for name in ("matplotlib", "matplotlib.pyplot", "numpy")}
    sys.modules.update({"matplotlib": matplotlib, "matplotlib.pyplot": pyplot, "numpy": numpy})
    try:
        spec.loader.exec_module(module)
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module


def _summary() -> dict[str, Any]:
    return {
        "unit": "percent_millionths",
        "integer_scale": 1_000_000,
        "per_seed": [],
        "estimate": {
            "sample_count": 5,
            "mean": {"numerator": 10_000_000, "denominator": 5, "rounded_half_even": 2_000_000},
            "ci95": {
                "status": "ESTIMATED",
                "method": "two_sided_student_t_95_conservative_table",
                "lower_floor": 1_000_000,
                "upper_ceiling": 3_000_000,
            },
        },
        "smoothing_performed": False,
    }


def _document() -> dict[str, Any]:
    seeds = [0, 1, 2, 3, 4]
    identities = ((1, 16), (2, 8), (2, 16), (2, 24), (2, 32), (4, 16), (8, 16))
    cells: list[dict[str, Any]] = []
    for failure_count, concurrency in identities:
        statistics: dict[str, Any] = {
            "schema": "moonkvsim.aegiskv.paper_sweep_statistics.v3",
            "status": "PASS",
            "cell_identity": {
                "failure_count": failure_count,
                "workflow_concurrency": concurrency,
            },
            "workload_fingerprint": "workload-fingerprint",
            "sampling_contract": {
                "seeds": seeds,
                "seed_count": 5,
                "smoothing_performed": False,
            },
            "provenance": {
                "observed_values_only": True,
                "trend_generation_performed": False,
            },
        }
        statistics["fingerprint"] = sha256_json(statistics)
        cells.append(
            {
                "failure_count": failure_count,
                "workflow_concurrency": concurrency,
                "statistics": statistics,
            }
        )
    document: dict[str, Any] = {
        "schema": "moonkvsim.aegiskv.paper_sweeps.v4",
        "status": "PASS",
        "evidence": {"paper_ready": False},
        "protocol": {
            "seeds": seeds,
            "seed_count": 5,
            "base_failure_count": 2,
            "base_workflow_concurrency": 16,
            "failure_counts": [1, 2, 4, 8],
            "workflow_concurrencies": [8, 16, 24, 32],
            "context_coverage": {"observed_128k_coverage": False},
        },
        "provenance": {"workload": {"fingerprint": "workload-fingerprint"}},
        "cells": cells,
        "raw_seed_cells": [{"must_not_be_used_by_figures": True}],
    }
    document["fingerprint"] = sha256_json(document)
    return document


def _refingerprint(document: dict[str, Any]) -> None:
    document.pop("fingerprint", None)
    document["fingerprint"] = sha256_json(document)


def test_generator_accepts_only_valid_multi_seed_aggregate_contract() -> None:
    generator = _load_generator()

    generator._validate_document(_document())


def test_generator_requires_matching_sensitivity_acceptance(tmp_path: Path) -> None:
    generator = _load_generator()
    document = _document()
    results = tmp_path / "paper-sweeps.json"
    results.write_text(json.dumps(document), encoding="utf-8")
    allowed = [f"FIGURE_5_{letter}" for letter in "ABCDEF"]
    gates = [
        {"gate": number, "status": "PASS", "evidence": {}}
        for number in range(1, 8)
    ]
    gates.append(
        {
            "gate": 8,
            "status": "PASS",
            "evidence": {"allowed_panel_ids": allowed},
        }
    )
    attempt = {
        "scenario": {"kind": "SENSITIVITY_SWEEP"},
        "artifact": {
            "fingerprint": document["fingerprint"],
            "sha256": generator._sha256_file(results),
        },
        "terminal_class": "VALID",
        "accepted_for_numerical_aggregates": True,
        "allowed_panel_ids": allowed,
        "gates": gates,
    }
    manifest = {
        "schema": "moonkvsim.aegiskv.qwen3-8b-acceptance-manifest.v1",
        "status": "PASS",
        "attempts": [attempt],
    }
    manifest["fingerprint"] = sha256_json(manifest)
    acceptance_path = tmp_path / "acceptance.json"
    acceptance_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert generator._validate_acceptance(
        document,
        results_path=results,
        acceptance_path=acceptance_path,
    ) == allowed

    attempt["allowed_panel_ids"] = allowed[:-1]
    manifest.pop("fingerprint")
    manifest["fingerprint"] = sha256_json(manifest)
    acceptance_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="authorization is inconsistent"):
        generator._validate_acceptance(
            document,
            results_path=results,
            acceptance_path=acceptance_path,
        )


def test_generator_rejects_legacy_single_seed_schema() -> None:
    generator = _load_generator()
    document = _document()
    document["schema"] = "moonkvsim.aegiskv.paper_sweeps.v1"
    _refingerprint(document)

    with pytest.raises(ValueError, match="multi-seed"):
        generator._validate_document(document)


def test_generator_rejects_fewer_than_five_seeds() -> None:
    generator = _load_generator()
    document = _document()
    document["protocol"]["seeds"] = [0, 1, 2, 3]
    document["protocol"]["seed_count"] = 4
    _refingerprint(document)

    with pytest.raises(ValueError, match="exact independent seed vector"):
        generator._validate_document(document)


def test_generator_rejects_smoothed_or_shaped_aggregate() -> None:
    generator = _load_generator()
    document = _document()
    statistics = document["cells"][0]["statistics"]
    statistics["sampling_contract"]["smoothing_performed"] = True
    statistics.pop("fingerprint")
    statistics["fingerprint"] = sha256_json(statistics)
    _refingerprint(document)

    with pytest.raises(ValueError, match="seed/smoothing"):
        generator._validate_document(document)


def test_generator_rejects_incomplete_or_extra_cell_grid() -> None:
    generator = _load_generator()
    missing = _document()
    missing["cells"].pop()
    _refingerprint(missing)

    with pytest.raises(ValueError, match="aggregate grid mismatch"):
        generator._validate_document(missing)

    extra = _document()
    extra_cell = deepcopy(extra["cells"][0])
    extra_cell["failure_count"] = 3
    statistics = extra_cell["statistics"]
    statistics["cell_identity"]["failure_count"] = 3
    statistics.pop("fingerprint")
    statistics["fingerprint"] = sha256_json(statistics)
    extra["cells"].append(extra_cell)
    _refingerprint(extra)

    with pytest.raises(ValueError, match="aggregate grid mismatch"):
        generator._validate_document(extra)


def test_generator_binds_outer_cell_identity_and_protocol_grid() -> None:
    generator = _load_generator()
    identity_drift = _document()
    identity_drift["cells"][0]["failure_count"] = 3
    _refingerprint(identity_drift)

    with pytest.raises(ValueError, match="does not match statistics identity"):
        generator._validate_document(identity_drift)

    protocol_drift = _document()
    protocol_drift["protocol"]["failure_counts"] = [1, 2, 4]
    _refingerprint(protocol_drift)

    with pytest.raises(ValueError, match="required F/C figure grid"):
        generator._validate_document(protocol_drift)

    protocol_type_drift = _document()
    protocol_type_drift["protocol"]["failure_counts"][0] = True
    _refingerprint(protocol_type_drift)

    with pytest.raises(ValueError, match=r"protocol\.failure_counts\[\]"):
        generator._validate_document(protocol_type_drift)


def test_generator_rejects_false_128k_coverage_claim() -> None:
    generator = _load_generator()
    document = _document()
    document["protocol"]["context_coverage"]["observed_128k_coverage"] = True
    _refingerprint(document)

    with pytest.raises(ValueError, match="128K"):
        generator._validate_document(document)


def test_summary_point_uses_aggregate_mean_and_two_sided_ci() -> None:
    generator = _load_generator()

    assert generator._summary_point(_summary()) == (2.0, 1.0, 3.0)


def test_canonical_failure_focus_summary_accepts_legacy_aggregate_path() -> None:
    generator = _load_generator()
    legacy = _summary()
    cell = {
        "statistics": {
            "wct_gain": {
                "failure_affected_p95": legacy,
            }
        }
    }

    assert generator._summary(cell, "wct_gain", "failure_focus_p95") == legacy


def test_plotting_code_never_reads_raw_seed_cells_or_shapes_trends() -> None:
    source = GENERATOR.read_text(encoding="utf-8")

    assert 'document["raw_seed_cells"]' not in source
    assert "np.interp" not in source
    assert "polyfit" not in source.lower()
    assert "savgol" not in source.lower()
    assert "fig1a_base_whole_workload_wct_cdf" in source
    assert "fig1b_base_failure_focus_wct_cdf" in source
    assert "fig1b_base_failure_affected_wct_cdf" not in source
    assert "workflow-seed observations" in source
    assert 'subset="failure_focus"' in source
    assert 'gain_path="failure_focus_p95"' in source
    assert "descriptive_variant_local_impacted_union_mean" in source
    assert "tier_selected_kv_tokens" in source
    assert "failure_impacted_workflow_count" in source
    assert "affected_workflow_count_ci" in source


def test_aggregate_fingerprint_validation_is_deterministic() -> None:
    generator = _load_generator()
    document = _document()
    copied = deepcopy(document)

    generator._validate_document(document)
    generator._validate_document(copied)
    assert document["fingerprint"] == copied["fingerprint"]


def test_output_directories_must_be_distinct_and_empty(tmp_path: Path) -> None:
    generator = _load_generator()
    output_dir = tmp_path / "figures"
    pdf_output_dir = tmp_path / "pdfs"

    generator._validate_output_directories(output_dir, pdf_output_dir)
    output_dir.mkdir()
    pdf_output_dir.mkdir()
    generator._validate_output_directories(output_dir, pdf_output_dir)

    (output_dir / "stale.pdf").write_bytes(b"stale")
    with pytest.raises(ValueError, match="must not exist or must be empty"):
        generator._validate_output_directories(output_dir, pdf_output_dir)
    with pytest.raises(ValueError, match="must be distinct"):
        generator._validate_output_directories(pdf_output_dir, pdf_output_dir)


def test_figure_manifest_is_derived_from_exact_actual_figure_set(tmp_path: Path) -> None:
    generator = _load_generator()
    output_dir = tmp_path / "figures"
    pdf_output_dir = tmp_path / "pdfs"
    output_dir.mkdir()
    pdf_output_dir.mkdir()
    for index, stem in enumerate(generator.EXPECTED_FIGURE_STEMS):
        png_bytes = f"png-{index}".encode()
        pdf_bytes = f"pdf-{index}".encode()
        (output_dir / f"{stem}.png").write_bytes(png_bytes)
        (output_dir / f"{stem}.pdf").write_bytes(pdf_bytes)
        (pdf_output_dir / f"{stem}.pdf").write_bytes(pdf_bytes)

    manifest_path, figure_count = generator._write_figure_manifest(output_dir, pdf_output_dir)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert figure_count == 23
    assert manifest["figure_count"] == 23
    assert len(manifest["figures"]) == 23
    assert {row["stem"] for row in manifest["figures"]} == set(generator.EXPECTED_FIGURE_STEMS)
    assert all(row["png_sha256"] for row in manifest["figures"])
    assert all(row["pdf_sha256"] == row["pdf_output_sha256"] for row in manifest["figures"])


def test_figure_manifest_rejects_missing_or_mismatched_files(tmp_path: Path) -> None:
    generator = _load_generator()
    output_dir = tmp_path / "figures"
    pdf_output_dir = tmp_path / "pdfs"
    output_dir.mkdir()
    pdf_output_dir.mkdir()
    for stem in generator.EXPECTED_FIGURE_STEMS[:-1]:
        (output_dir / f"{stem}.png").write_bytes(b"png")
        (output_dir / f"{stem}.pdf").write_bytes(b"pdf")
        (pdf_output_dir / f"{stem}.pdf").write_bytes(b"pdf")

    with pytest.raises(ValueError, match="generated figure set mismatch"):
        generator._write_figure_manifest(output_dir, pdf_output_dir)

    final_stem = generator.EXPECTED_FIGURE_STEMS[-1]
    (output_dir / f"{final_stem}.png").write_bytes(b"png")
    (output_dir / f"{final_stem}.pdf").write_bytes(b"pdf")
    (pdf_output_dir / f"{final_stem}.pdf").write_bytes(b"different")

    with pytest.raises(ValueError, match="PDF copy hash mismatch"):
        generator._write_figure_manifest(output_dir, pdf_output_dir)
