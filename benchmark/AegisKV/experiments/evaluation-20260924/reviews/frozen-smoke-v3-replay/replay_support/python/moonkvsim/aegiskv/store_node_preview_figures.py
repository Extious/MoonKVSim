"""Render and audit the focused AegisKV Store-node E2 preview."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Final, cast

from moonkvsim.common.hash import sha256_json

EVIDENCE_FOOTER: Final = (
    "E2 modeled/preliminary · GlobalDES only · not calibrated · no physical experiment"
)
BUCKETS: Final = ("8k", "32k", "64k", "96k", "128k")
VARIANTS: Final = (
    "store_node_count=1",
    "store_node_count=2",
    "store_node_count=4",
)
COLORS: Final = {
    "store_node_count=1": "#2563eb",
    "store_node_count=2": "#7c3aed",
    "store_node_count=4": "#dc2626",
}
WIDTH: Final = 1320
HEIGHT: Final = 800


class StoreNodePreviewError(ValueError):
    """Focused Store-node input or output failed closed."""


@dataclass(frozen=True, slots=True)
class StoreNodePreviewResult:
    output_dir: Path
    manifest_path: Path
    figure_path: Path
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class StoreNodePreviewAudit:
    status: str
    matrix_manifest_fingerprint: str
    result_count: int
    pair_count: int
    figure_count: int
    figure_manifest_sha256: str
    physical_execution: bool
    slurm_used: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "moonkvsim.aegiskv.store_node_preview_audit.v1",
            "status": self.status,
            "matrix_manifest_fingerprint": self.matrix_manifest_fingerprint,
            "result_count": self.result_count,
            "pair_count": self.pair_count,
            "figure_count": self.figure_count,
            "figure_manifest_sha256": self.figure_manifest_sha256,
            "physical_execution": self.physical_execution,
            "slurm_used": self.slurm_used,
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_object(path: Path) -> dict[str, Any]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise StoreNodePreviewError(f"expected JSON object: {path}")
    return cast(dict[str, Any], value)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value: object = json.loads(line)
        if not isinstance(value, dict):
            raise StoreNodePreviewError(f"row {line_number} is not an object: {path}")
        rows.append(cast(dict[str, Any], value))
    return rows


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _metric(row: Mapping[str, Any], *path: str) -> int:
    value: object = row
    for key in path:
        if not isinstance(value, Mapping):
            raise StoreNodePreviewError(f"metric path is missing: {'/'.join(path)}")
        value = value.get(key)
    if type(value) is not int:
        raise StoreNodePreviewError(f"metric is not an integer: {'/'.join(path)}")
    return value


def _evidence_valid(value: object) -> bool:
    return isinstance(value, Mapping) and value == {
        "calibration": "not_calibrated",
        "class": "E2",
        "formal_use_allowed": False,
        "paper_ready": False,
        "physical_execution": False,
        "physical_timing_claim_allowed": False,
        "scope": "modeled/preliminary",
        "slurm_used": False,
    }


def _verify_matrix(matrix_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = _json_object(matrix_dir / "manifest.json")
    completeness = _json_object(matrix_dir / "completeness.json")
    protocol = _json_object(matrix_dir / "protocol.json")
    provenance = _json_object(matrix_dir / "provenance.json")
    rows = _jsonl(matrix_dir / "results.jsonl")
    pairs = _jsonl(matrix_dir / "pair-audit.jsonl")
    evidence = manifest.get("evidence")
    if not _evidence_valid(evidence):
        raise StoreNodePreviewError("Store-node matrix evidence boundary failed")
    if manifest.get("status") != "PASS" or manifest.get("result_count") != 120:
        raise StoreNodePreviewError("Store-node matrix result cross product failed")
    if manifest.get("pair_count") != 60 or len(rows) != 120 or len(pairs) != 60:
        raise StoreNodePreviewError("Store-node matrix artifact counts drifted")
    if completeness.get("status") != "PASS" or completeness.get("all_pairs_exact") is not True:
        raise StoreNodePreviewError("Store-node matrix completeness failed")
    execution = protocol.get("execution")
    if not isinstance(execution, Mapping) or execution.get("variant_ids") != list(VARIANTS):
        raise StoreNodePreviewError("Store-node protocol variant catalog drifted")
    provenance_execution = provenance.get("execution")
    if not isinstance(provenance_execution, Mapping) or any(
        provenance_execution.get(field) is not False
        for field in (
            "wall_clock_measurements_recorded",
            "physical_components_executed",
            "slurm_used",
        )
    ):
        raise StoreNodePreviewError("Store-node provenance crossed E2 scope")
    artifact_hashes = manifest.get("artifact_hashes")
    if not isinstance(artifact_hashes, Mapping):
        raise StoreNodePreviewError("Store-node manifest lacks artifact hashes")
    for name, raw in artifact_hashes.items():
        if not isinstance(name, str) or not isinstance(raw, Mapping):
            raise StoreNodePreviewError("Store-node artifact hash entry is malformed")
        if _sha256_file(matrix_dir / name) != raw.get("sha256"):
            raise StoreNodePreviewError(f"Store-node artifact hash drifted: {name}")
    expected_cells = {
        (variant, bucket, scenario, seed, repetition)
        for variant in VARIANTS
        for bucket in BUCKETS
        for scenario in ("no_failure", "gpu_failure")
        for seed in (0, 1)
        for repetition in ("A", "B")
    }
    actual_cells: set[tuple[str, str, str, int, str]] = set()
    for row in rows:
        variant = str(row.get("variant_id"))
        cell = (
            variant,
            str(row.get("context_bucket")),
            str(row.get("scenario")),
            int(row.get("seed", -1)),
            str(row.get("repetition")),
        )
        actual_cells.add(cell)
        payload = row.get("payload")
        if not isinstance(payload, Mapping):
            raise StoreNodePreviewError("Store-node row payload is missing")
        scope = payload.get("execution_scope")
        if not isinstance(scope, Mapping) or scope != {
            "cpu_metadata_only": True,
            "cuda_used": False,
            "network_io_used": False,
            "slurm_used": False,
        }:
            raise StoreNodePreviewError("Store-node row used a forbidden execution path")
        node_count = int(variant.rsplit("=", 1)[1])
        resource_model = payload.get("resource_model")
        if not isinstance(resource_model, Mapping):
            raise StoreNodePreviewError("Store-node resource model is missing")
        segments = resource_model.get("store_dram_segments")
        if resource_model.get("store_node_count") != node_count or not isinstance(
            segments, list
        ):
            raise StoreNodePreviewError("Store-node deployment binding drifted")
        if len(segments) != node_count or len(set(map(str, segments))) != node_count:
            raise StoreNodePreviewError("Store-node segment identities are incomplete")
        metrics = payload.get("metrics")
        if not isinstance(metrics, Mapping):
            raise StoreNodePreviewError("Store-node metrics are missing")
        resource_cost = metrics.get("resource_cost")
        pool_audit = metrics.get("pool_audit")
        if not isinstance(resource_cost, Mapping) or not isinstance(pool_audit, Mapping):
            raise StoreNodePreviewError("Store-node resource audit is missing")
        by_segment = resource_cost.get("store_dram_by_segment")
        store_audit = pool_audit.get("store_dram")
        if not isinstance(by_segment, Mapping) or len(by_segment) != node_count:
            raise StoreNodePreviewError("Store-node per-segment ledger is incomplete")
        if not isinstance(store_audit, Mapping) or store_audit.get("valid") is not True:
            raise StoreNodePreviewError("Store-node aggregate ledger is invalid")
        capacities = []
        for segment in by_segment.values():
            if not isinstance(segment, Mapping) or segment.get("valid") is not True:
                raise StoreNodePreviewError("Store-node segment ledger is invalid")
            capacity = segment.get("capacity_bytes")
            if type(capacity) is not int:
                raise StoreNodePreviewError("Store-node segment capacity is malformed")
            capacities.append(capacity)
        if sum(capacities) != store_audit.get("capacity_bytes"):
            raise StoreNodePreviewError("Store-node capacity partition does not conserve")
        if pool_audit.get("pending_destination_bytes_final") != 0:
            raise StoreNodePreviewError("Store-node row leaked a pending destination")
        if resource_cost.get("source_pin_count_final") != 0:
            raise StoreNodePreviewError("Store-node row leaked a source pin")
    if actual_cells != expected_cells:
        raise StoreNodePreviewError("Store-node result cells drifted")
    if any(
        pair.get("status") != "PASS"
        or pair.get("payload_sha256_exact_match") is not True
        or pair.get("journal_sha256_exact_match") is not True
        for pair in pairs
    ):
        raise StoreNodePreviewError("Store-node A/B determinism audit failed")
    return manifest, rows


class _Svg:
    def __init__(self) -> None:
        self.root = ET.Element(
            "svg",
            {
                "xmlns": "http://www.w3.org/2000/svg",
                "width": str(WIDTH),
                "height": str(HEIGHT),
                "viewBox": f"0 0 {WIDTH} {HEIGHT}",
                "role": "img",
            },
        )
        ET.SubElement(self.root, "title").text = (
            "Store-node scaling under modeled GlobalDES contention"
        )
        style = ET.SubElement(self.root, "style")
        style.text = (
            "text{font-family:DejaVu Sans,Arial,sans-serif;fill:#111827}"
            ".title{font-size:26px;font-weight:700}.sub{font-size:13px;fill:#475569}"
            ".panel{font-size:15px;font-weight:700}.tick{font-size:11px;fill:#475569}"
            ".label{font-size:12px;font-weight:650}.footer{font-size:13px;"
            "font-weight:700;fill:#991b1b}"
        )
        self.rect(0, 0, WIDTH, HEIGHT, "#ffffff")

    def rect(self, x: float, y: float, w: float, h: float, fill: str, **attrs: str) -> None:
        ET.SubElement(
            self.root,
            "rect",
            {"x": str(x), "y": str(y), "width": str(w), "height": str(h), "fill": fill, **attrs},
        )

    def line(self, x1: float, y1: float, x2: float, y2: float, **attrs: str) -> None:
        ET.SubElement(
            self.root,
            "line",
            {"x1": str(x1), "y1": str(y1), "x2": str(x2), "y2": str(y2), **attrs},
        )

    def text(self, x: float, y: float, value: str, css: str = "") -> None:
        attrs = {"x": str(x), "y": str(y)}
        if css:
            attrs["class"] = css
        ET.SubElement(self.root, "text", attrs).text = value

    def point(
        self,
        x: float,
        y: float,
        *,
        color: str,
        point_id: str,
        rows: Sequence[Mapping[str, Any]],
    ) -> None:
        group = ET.SubElement(
            self.root,
            "g",
            {
                "data-point-id": point_id,
                "data-run-ids": ";".join(str(row["run_id"]) for row in rows),
                "data-result-hashes": ";".join(
                    str(row["payload_sha256"]) for row in rows
                ),
            },
        )
        ET.SubElement(group, "circle", {"cx": str(x), "cy": str(y), "r": "4.5", "fill": color})

    def write(self, path: Path) -> None:
        ET.indent(self.root, space="  ")
        ET.ElementTree(self.root).write(path, encoding="utf-8", xml_declaration=True)


def _network_byte_ns(row: Mapping[str, Any]) -> int:
    values = cast(
        Mapping[str, int],
        row["payload"]["metrics"]["resource_cost"]["network_byte_ns"],
    )
    return sum(values.values())


def _render(rows: Sequence[Mapping[str, Any]], output: Path) -> dict[str, Any]:
    by_key = {
        (
            str(row["variant_id"]),
            str(row["context_bucket"]),
            str(row["scenario"]),
            int(row["seed"]),
        ): row
        for row in rows
        if row.get("repetition") == "A"
    }
    svg = _Svg()
    svg.text(44, 40, "Store-node scaling under modeled GlobalDES contention", "title")
    svg.text(
        44,
        66,
        "Fixed 64-GiB total Store budget · GPU_FAILURE · seeds 0/1 · A/B exact",
        "sub",
    )
    panels = ((44, 105, 390, 560), (465, 105, 390, 560), (886, 105, 390, 560))
    for x, y, width, height in panels:
        svg.rect(x, y, width, height, "#f8fafc", stroke="#cbd5e1", **{"stroke-width": "1"})
    svg.text(62, 136, "A  Whole-workload WCT delta vs 1 node (%)", "panel")
    svg.text(483, 136, "B  Network byte-time ratio vs 1 node", "panel")
    svg.text(904, 136, "C  128K recovery token composition", "panel")
    variants = VARIANTS[1:]
    left, top, plot_w, plot_h = 82, 175, 320, 410
    wct_min, wct_max = -0.02, 0.30
    for tick in (-0.02, 0.0, 0.1, 0.2, 0.3):
        grid_y = top + plot_h - (tick - wct_min) / (wct_max - wct_min) * plot_h
        svg.line(
            left,
            grid_y,
            left + plot_w,
            grid_y,
            stroke="#94a3b8" if tick == 0 else "#e2e8f0",
            **{"stroke-width": "1.5" if tick == 0 else "1"},
        )
        svg.text(left - 38, grid_y + 4, f"{tick:.2f}", "tick")
    line_points: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    bindings = []
    for bucket_index, bucket in enumerate(BUCKETS):
        x_a = left + bucket_index * plot_w / 4
        x_b = 503 + bucket_index * plot_w / 4
        svg.text(x_a - 10, top + plot_h + 22, bucket, "tick")
        svg.text(x_b - 10, top + plot_h + 22, bucket, "tick")
        for variant in variants:
            selected = [by_key[(variant, bucket, "gpu_failure", seed)] for seed in (0, 1)]
            deltas = []
            ratios = []
            for seed, row in zip((0, 1), selected, strict=True):
                baseline = by_key[(VARIANTS[0], bucket, "gpu_failure", seed)]
                wct = _metric(row, "payload", "metrics", "workflow_completion_time_ns", "mean")
                base_wct = _metric(
                    baseline,
                    "payload",
                    "metrics",
                    "workflow_completion_time_ns",
                    "mean",
                )
                deltas.append(100.0 * (wct - base_wct) / base_wct)
                ratios.append(_network_byte_ns(row) / _network_byte_ns(baseline))
            delta_mean = sum(deltas) / 2
            y_a = top + plot_h - (delta_mean - wct_min) / (wct_max - wct_min) * plot_h
            y_low = top + plot_h - (min(deltas) - wct_min) / (wct_max - wct_min) * plot_h
            y_high = top + plot_h - (max(deltas) - wct_min) / (wct_max - wct_min) * plot_h
            svg.line(x_a, y_low, x_a, y_high, stroke=COLORS[variant], **{"stroke-width": "2"})
            svg.point(
                x_a,
                y_a,
                color=COLORS[variant],
                point_id=f"wct:{variant}:{bucket}",
                rows=selected,
            )
            line_points[("wct", variant)].append((x_a, y_a))
            ratio_mean = sum(ratios) / 2
            y_b = top + plot_h - (ratio_mean - 0.3) / 0.5 * plot_h
            y_b_low = top + plot_h - (min(ratios) - 0.3) / 0.5 * plot_h
            y_b_high = top + plot_h - (max(ratios) - 0.3) / 0.5 * plot_h
            svg.line(x_b, y_b_low, x_b, y_b_high, stroke=COLORS[variant], **{"stroke-width": "2"})
            svg.point(
                x_b,
                y_b,
                color=COLORS[variant],
                point_id=f"network:{variant}:{bucket}",
                rows=selected,
            )
            line_points[("network", variant)].append((x_b, y_b))
            bindings.append(
                {
                    "variant": variant,
                    "context_bucket": bucket,
                    "run_ids": [str(row["run_id"]) for row in selected],
                    "payload_sha256": [str(row["payload_sha256"]) for row in selected],
                    "wct_delta_percent_mean": delta_mean,
                    "wct_delta_percent_seed_range": [min(deltas), max(deltas)],
                    "network_byte_time_ratio_mean": ratio_mean,
                    "network_byte_time_ratio_seed_range": [min(ratios), max(ratios)],
                }
            )
    for variant in variants:
        for metric in ("wct", "network"):
            for first, second in pairwise(line_points[(metric, variant)]):
                svg.line(
                    first[0],
                    first[1],
                    second[0],
                    second[1],
                    stroke=COLORS[variant],
                    **{"stroke-width": "2"},
                )
    for tick in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        grid_y = top + plot_h - (tick - 0.3) / 0.5 * plot_h
        svg.line(503, grid_y, 823, grid_y, stroke="#e2e8f0", **{"stroke-width": "1"})
        svg.text(468, grid_y + 4, f"{tick:.1f}x", "tick")

    bar_left, bar_top, bar_w, bar_h = 930, 175, 300, 410
    max_tokens = 130_000
    for tick in (0, 32_000, 64_000, 96_000, 128_000):
        grid_y = bar_top + bar_h - tick / max_tokens * bar_h
        svg.line(
            bar_left,
            grid_y,
            bar_left + bar_w,
            grid_y,
            stroke="#e2e8f0",
            **{"stroke-width": "1"},
        )
        svg.text(bar_left - 44, grid_y + 4, f"{tick // 1000}K", "tick")
    recovery_bindings = []
    for index, variant in enumerate(VARIANTS):
        selected = [by_key[(variant, "128k", "gpu_failure", seed)] for seed in (0, 1)]
        restored = [
            _metric(row, "payload", "metrics", "restored_tokens", "total")
            for row in selected
        ]
        recomputed = [
            _metric(row, "payload", "metrics", "recompute_tokens_after_failure")
            for row in selected
        ]
        restored_mean = sum(restored) / 2
        recomputed_mean = sum(recomputed) / 2
        x = bar_left + 26 + index * 98
        restored_h = restored_mean / max_tokens * bar_h
        recompute_h = recomputed_mean / max_tokens * bar_h
        svg.rect(x, bar_top + bar_h - restored_h, 56, restored_h, "#16a34a", rx="4")
        svg.rect(
            x,
            bar_top + bar_h - restored_h - recompute_h,
            56,
            recompute_h,
            "#f59e0b",
            rx="4",
        )
        svg.text(x + 8, bar_top + bar_h + 22, variant.rsplit("=", 1)[1] + " node", "tick")
        recovery_bindings.append(
            {
                "variant": variant,
                "context_bucket": "128k",
                "run_ids": [str(row["run_id"]) for row in selected],
                "payload_sha256": [str(row["payload_sha256"]) for row in selected],
                "restored_tokens_mean": restored_mean,
                "recomputed_tokens_mean": recomputed_mean,
                "restored_tokens_seed_range": [min(restored), max(restored)],
            }
        )
    svg.rect(902, 620, 16, 8, "#16a34a")
    svg.text(925, 630, "restored", "tick")
    svg.rect(1005, 620, 16, 8, "#f59e0b")
    svg.text(1028, 630, "recomputed", "tick")
    for index, variant in enumerate(variants):
        x = 78 + index * 175
        svg.rect(x, 620, 16, 8, COLORS[variant])
        svg.text(x + 23, 630, variant.rsplit("=", 1)[1] + " Store nodes", "tick")
    svg.text(44, 732, EVIDENCE_FOOTER, "footer")
    svg.text(
        44,
        758,
        "Total Store capacity is fixed; whiskers are seed-0/1 range; repeat B is replay.",
        "sub",
    )
    svg.write(output)
    return {
        "aggregate_bindings": bindings,
        "recovery_bindings": recovery_bindings,
        "interpretation": {
            "store_total_capacity_bytes": 64 * 1024**3,
            "store_capacity_held_fixed": True,
            "wct_direction": "positive_is_slower_than_one_store_node",
            "network_ratio_baseline": "one_store_node_same_bucket_scenario_seed",
            "seed_count": 2,
            "repeat_b_used_as_sample": False,
            "physical_timing_claim_allowed": False,
        },
    }


def generate_store_node_preview(
    *, matrix_dir: Path, output_dir: Path, generator_source: Path
) -> StoreNodePreviewResult:
    if output_dir.exists():
        raise StoreNodePreviewError(f"existing figure output is forbidden: {output_dir}")
    matrix_manifest, rows = _verify_matrix(matrix_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.staging-", dir=output_dir.parent)
    )
    try:
        figure_path = staging / "f18-store-node-sensitivity.svg"
        bindings = _render(rows, figure_path)
        document: dict[str, Any] = {
            "schema": "moonkvsim.aegiskv.store_node_preview_manifest.v1",
            "status": "PASS",
            "evidence": matrix_manifest["evidence"],
            "source_matrix": {
                "path": matrix_dir.as_posix(),
                "manifest_fingerprint": matrix_manifest["fingerprint"],
                "manifest_sha256": _sha256_file(matrix_dir / "manifest.json"),
                "results_sha256": _sha256_file(matrix_dir / "results.jsonl"),
                "result_count": matrix_manifest["result_count"],
                "pair_count": matrix_manifest["pair_count"],
            },
            "generator": {
                "path": generator_source.as_posix(),
                "sha256": _sha256_file(generator_source),
                "physical_execution": False,
            },
            "figure": {
                "id": "F18",
                "path": figure_path.name,
                "sha256": _sha256_file(figure_path),
                "size_bytes": figure_path.stat().st_size,
                **bindings,
            },
            "physical_execution": False,
            "slurm_used": False,
        }
        document["fingerprint"] = sha256_json(document)
        manifest_path = staging / "manifest.json"
        _write_json(manifest_path, document)
        staging.replace(output_dir)
        return StoreNodePreviewResult(
            output_dir=output_dir,
            manifest_path=output_dir / "manifest.json",
            figure_path=output_dir / figure_path.name,
            manifest_sha256=_sha256_file(output_dir / "manifest.json"),
        )
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def audit_store_node_preview(
    *, matrix_dir: Path, figure_dir: Path
) -> StoreNodePreviewAudit:
    matrix_manifest, _rows = _verify_matrix(matrix_dir)
    figure_manifest = _json_object(figure_dir / "manifest.json")
    if figure_manifest.get("status") != "PASS":
        raise StoreNodePreviewError("Store-node figure manifest is not passing")
    source = figure_manifest.get("source_matrix")
    if not isinstance(source, Mapping) or source.get("manifest_fingerprint") != matrix_manifest.get(
        "fingerprint"
    ):
        raise StoreNodePreviewError("Store-node figure source binding drifted")
    figure = figure_manifest.get("figure")
    if not isinstance(figure, Mapping) or figure.get("id") != "F18":
        raise StoreNodePreviewError("Store-node figure entry is malformed")
    figure_path = figure_dir / str(figure.get("path"))
    if _sha256_file(figure_path) != figure.get("sha256"):
        raise StoreNodePreviewError("Store-node figure SHA-256 drifted")
    root = ET.parse(figure_path).getroot()
    text = " ".join("" if item.text is None else item.text for item in root.iter())
    if EVIDENCE_FOOTER not in text:
        raise StoreNodePreviewError("Store-node figure lost its evidence footer")
    if not root.findall(".//{http://www.w3.org/2000/svg}g"):
        raise StoreNodePreviewError("Store-node figure has no result-bound points")
    return StoreNodePreviewAudit(
        status="PASS",
        matrix_manifest_fingerprint=str(matrix_manifest["fingerprint"]),
        result_count=int(matrix_manifest["result_count"]),
        pair_count=int(matrix_manifest["pair_count"]),
        figure_count=1,
        figure_manifest_sha256=_sha256_file(figure_dir / "manifest.json"),
        physical_execution=False,
        slurm_used=False,
    )
