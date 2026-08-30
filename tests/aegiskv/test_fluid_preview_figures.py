from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from moonkvsim.aegiskv.fluid_preview_figures import (
    EVIDENCE_FOOTER,
    FluidPreviewError,
    audit_fluid_core_preview,
    generate_fluid_core_preview,
)

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "benchmark/AegisKV/experiments/results/e2-fluid-core-v2"


def test_fluid_core_preview_is_deterministic_source_bound_and_offline(
    tmp_path: Path,
) -> None:
    first = generate_fluid_core_preview(
        matrix_dir=MATRIX,
        output_dir=tmp_path / "first",
    )
    second = generate_fluid_core_preview(
        matrix_dir=MATRIX,
        output_dir=tmp_path / "second",
    )

    assert first.manifest_sha256 == second.manifest_sha256
    assert first.manifest_path.read_bytes() == second.manifest_path.read_bytes()
    manifest = json.loads(first.manifest_path.read_text())
    assert manifest["status"] == "PASS"
    assert manifest["figure_count"] == 3
    assert manifest["evidence"]["physical_execution"] is False
    assert manifest["evidence"]["slurm_used"] is False
    assert {item["figure_id"] for item in manifest["figures"]} == {
        "F3V2",
        "F5V2",
        "F16",
    }

    for entry in manifest["figures"]:
        svg_path = first.output_dir / entry["svg"]["file"]
        provenance_path = first.output_dir / entry["provenance"]["file"]
        root = ET.fromstring(svg_path.read_bytes())
        assert root.tag.endswith("svg")
        assert EVIDENCE_FOOTER in svg_path.read_text()
        assert root.findall(".//*[@data-run-id]")
        provenance = json.loads(provenance_path.read_text())
        assert provenance["physical_execution"] is False
        assert provenance["slurm_used"] is False
        assert provenance["representative_binding"]["run_id"].endswith("repeat-A")

    audit = audit_fluid_core_preview(matrix_dir=MATRIX, figure_dir=first.output_dir)
    assert audit.status == "PASS"
    assert audit.matrix_result_count == 280
    assert audit.matrix_pair_count == 140
    assert audit.figure_count == 3
    assert audit.physical_execution is False
    assert audit.slurm_used is False

    first_svg = next(first.output_dir.glob("*.svg"))
    first_svg.write_text(first_svg.read_text().replace("GlobalDES", "TamperedDES", 1))
    with pytest.raises(FluidPreviewError, match="hash or size mismatch"):
        audit_fluid_core_preview(matrix_dir=MATRIX, figure_dir=first.output_dir)


def test_fluid_core_preview_refuses_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "existing"
    target.mkdir()
    with pytest.raises(FluidPreviewError, match="already exists"):
        generate_fluid_core_preview(matrix_dir=MATRIX, output_dir=target)
