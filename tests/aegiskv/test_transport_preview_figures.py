from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from moonkvsim.aegiskv.transport_preview_figures import (
    EVIDENCE_FOOTER,
    TransportPreviewError,
    audit_transport_preview,
    generate_transport_preview,
)

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "benchmark/AegisKV/experiments/results/e2-transport-v1"
GENERATOR = ROOT / "python/moonkvsim/aegiskv/transport_preview_figures.py"


def test_transport_preview_is_deterministic_source_bound_and_offline(
    tmp_path: Path,
) -> None:
    first = generate_transport_preview(
        matrix_dir=MATRIX,
        output_dir=tmp_path / "first",
        generator_source=GENERATOR,
    )
    second = generate_transport_preview(
        matrix_dir=MATRIX,
        output_dir=tmp_path / "second",
        generator_source=GENERATOR,
    )

    assert first.manifest_sha256 == second.manifest_sha256
    assert first.figure_path.read_bytes() == second.figure_path.read_bytes()
    manifest = json.loads(first.manifest_path.read_text())
    assert manifest["status"] == "PASS"
    assert manifest["evidence"]["physical_execution"] is False
    assert manifest["physical_execution"] is False
    assert manifest["slurm_used"] is False
    assert manifest["figure"]["id"] == "F17"
    assert manifest["figure"]["interpretation"]["repeat_b_used_as_sample"] is False

    root = ET.fromstring(first.figure_path.read_bytes())
    assert root.tag.endswith("svg")
    assert EVIDENCE_FOOTER in first.figure_path.read_text()
    assert root.findall(".//*[@data-run-ids]")

    audit = audit_transport_preview(matrix_dir=MATRIX, figure_dir=first.output_dir)
    assert audit.status == "PASS"
    assert audit.result_count == 120
    assert audit.pair_count == 60
    assert audit.figure_count == 1
    assert audit.physical_execution is False
    assert audit.slurm_used is False

    first.figure_path.write_text(
        first.figure_path.read_text().replace("GlobalDES", "TamperedDES", 1)
    )
    with pytest.raises(TransportPreviewError, match="SHA-256 drifted"):
        audit_transport_preview(matrix_dir=MATRIX, figure_dir=first.output_dir)


def test_transport_preview_refuses_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "existing"
    target.mkdir()
    with pytest.raises(TransportPreviewError, match="existing figure output"):
        generate_transport_preview(
            matrix_dir=MATRIX,
            output_dir=target,
            generator_source=GENERATOR,
        )
