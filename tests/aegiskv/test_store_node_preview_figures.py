from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from moonkvsim.aegiskv.store_node_preview_figures import (
    EVIDENCE_FOOTER,
    StoreNodePreviewError,
    audit_store_node_preview,
    generate_store_node_preview,
)

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "benchmark/AegisKV/experiments/results/e2-store-nodes-v1"
GENERATOR = ROOT / "python/moonkvsim/aegiskv/store_node_preview_figures.py"


def test_store_node_preview_is_deterministic_source_bound_and_offline(
    tmp_path: Path,
) -> None:
    first = generate_store_node_preview(
        matrix_dir=MATRIX,
        output_dir=tmp_path / "first",
        generator_source=GENERATOR,
    )
    second = generate_store_node_preview(
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
    assert manifest["figure"]["id"] == "F18"
    interpretation = manifest["figure"]["interpretation"]
    assert interpretation["store_capacity_held_fixed"] is True
    assert interpretation["repeat_b_used_as_sample"] is False

    root = ET.fromstring(first.figure_path.read_bytes())
    assert root.tag.endswith("svg")
    assert EVIDENCE_FOOTER in first.figure_path.read_text()
    assert root.findall(".//*[@data-run-ids]")

    audit = audit_store_node_preview(matrix_dir=MATRIX, figure_dir=first.output_dir)
    assert audit.status == "PASS"
    assert audit.result_count == 120
    assert audit.pair_count == 60
    assert audit.figure_count == 1
    assert audit.physical_execution is False
    assert audit.slurm_used is False

    first.figure_path.write_text(
        first.figure_path.read_text().replace("GlobalDES", "TamperedDES", 1)
    )
    with pytest.raises(StoreNodePreviewError, match="SHA-256 drifted"):
        audit_store_node_preview(matrix_dir=MATRIX, figure_dir=first.output_dir)


def test_store_node_preview_refuses_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "existing"
    target.mkdir()
    with pytest.raises(StoreNodePreviewError, match="existing figure output"):
        generate_store_node_preview(
            matrix_dir=MATRIX,
            output_dir=target,
            generator_source=GENERATOR,
        )
