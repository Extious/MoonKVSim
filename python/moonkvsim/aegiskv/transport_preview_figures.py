"""Render and audit the focused AegisKV Store-transport E2 preview."""

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
TRANSPORTS: Final = (
    "store_transport=RDMA_GDR",
    "store_transport=RDMA_HOST_STAGED",
    "store_transport=TCP_HOST_STAGED",
)
COLORS: Final = {
    "store_transport=RDMA_GDR": "#2563eb",
    "store_transport=RDMA_HOST_STAGED": "#7c3aed",
    "store_transport=TCP_HOST_STAGED": "#dc2626",
}
LABELS: Final = {
    "store_transport=RDMA_GDR": "RDMA GDR",
    "store_transport=RDMA_HOST_STAGED": "RDMA staged",
    "store_transport=TCP_HOST_STAGED": "TCP staged",
}
WIDTH: Final = 1320
HEIGHT: Final = 800


class TransportPreviewError(ValueError):
    """Focused transport input or output failed closed."""


@dataclass(frozen=True, slots=True)
class TransportPreviewResult:
    output_dir: Path
    manifest_path: Path
    figure_path: Path
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class TransportPreviewAudit:
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
            "schema": "moonkvsim.aegiskv.transport_preview_audit.v1",
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
        raise TransportPreviewError(f"expected JSON object: {path}")
    return cast(dict[str, Any], value)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value: object = json.loads(line)
        if not isinstance(value, dict):
            raise TransportPreviewError(f"row {line_number} is not an object: {path}")
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
    if manifest.get("status") != "PASS" or not _evidence_valid(manifest.get("evidence")):
        raise TransportPreviewError("transport matrix evidence boundary failed")
    if manifest.get("result_count") != 120 or manifest.get("pair_count") != 60:
        raise TransportPreviewError("transport matrix cross product is incomplete")
    if len(rows) != 120 or len(pairs) != 60:
        raise TransportPreviewError("transport matrix artifact counts drifted")
    if completeness.get("status") != "PASS" or not completeness.get("all_pairs_exact"):
        raise TransportPreviewError("transport matrix completeness failed")
    execution = protocol.get("execution")
    if not isinstance(execution, Mapping) or execution.get("variant_ids") != list(TRANSPORTS):
        raise TransportPreviewError("transport protocol variant catalog drifted")
    provenance_execution = provenance.get("execution")
    if not isinstance(provenance_execution, Mapping) or any(
        provenance_execution.get(field) is not False
        for field in (
            "wall_clock_measurements_recorded",
            "physical_components_executed",
            "slurm_used",
        )
    ):
        raise TransportPreviewError("transport provenance crossed the E2 scope")
    artifact_hashes = manifest.get("artifact_hashes")
    if not isinstance(artifact_hashes, Mapping):
        raise TransportPreviewError("transport manifest lacks artifact hashes")
    for name, raw in artifact_hashes.items():
        if not isinstance(name, str) or not isinstance(raw, Mapping):
            raise TransportPreviewError("transport artifact hash entry is malformed")
        if _sha256_file(matrix_dir / name) != raw.get("sha256"):
            raise TransportPreviewError(f"transport artifact hash drifted: {name}")
    expected_cells = {
        (transport, bucket, scenario, seed, repetition)
        for transport in TRANSPORTS
        for bucket in BUCKETS
        for scenario in ("no_failure", "gpu_failure")
        for seed in (0, 1)
        for repetition in ("A", "B")
    }
    actual_cells: set[tuple[str, str, str, int, str]] = set()
    for row in rows:
        cell = (
            str(row.get("variant_id")),
            str(row.get("context_bucket")),
            str(row.get("scenario")),
            int(row.get("seed", -1)),
            str(row.get("repetition")),
        )
        actual_cells.add(cell)
        payload = row.get("payload")
        if not isinstance(payload, Mapping):
            raise TransportPreviewError("transport result payload is missing")
        scope = payload.get("execution_scope")
        if not isinstance(scope, Mapping) or scope != {
            "cpu_metadata_only": True,
            "cuda_used": False,
            "network_io_used": False,
            "slurm_used": False,
        }:
            raise TransportPreviewError("transport row used a forbidden execution path")
        metrics = payload.get("metrics")
        if not isinstance(metrics, Mapping):
            raise TransportPreviewError("transport row metrics are missing")
        resource_cost = metrics.get("resource_cost")
        if not isinstance(resource_cost, Mapping):
            raise TransportPreviewError("transport resource cost is missing")
        host_peak = resource_cost.get("host_dram_staging_peak_bytes")
        if type(host_peak) is not int:
            raise TransportPreviewError("Host staging peak is malformed")
        if cell[0] == TRANSPORTS[0] and host_peak != 0:
            raise TransportPreviewError("GDR silently charged Host staging")
        if cell[0] != TRANSPORTS[0] and host_peak <= 0:
            raise TransportPreviewError("Host-staged path did not charge staging")
        if resource_cost.get("source_pin_count_final") != 0:
            raise TransportPreviewError("transport row leaked a source pin")
        host_stacks = resource_cost.get("host_dram_staging_by_gpu")
        if not isinstance(host_stacks, Mapping):
            raise TransportPreviewError("Host staging ledgers are missing")
        for stack in host_stacks.values():
            if not isinstance(stack, Mapping) or stack.get("valid") is not True:
                raise TransportPreviewError("Host staging ledger is invalid")
            final = stack.get("final_accounts")
            if not isinstance(final, Mapping) or final.get("TRANSFER_STAGING") != 0:
                raise TransportPreviewError("Host staging ledger did not return to zero")
    if actual_cells != expected_cells:
        raise TransportPreviewError("transport result cells drifted")
    if any(
        pair.get("status") != "PASS"
        or pair.get("payload_sha256_exact_match") is not True
        or pair.get("journal_sha256_exact_match") is not True
        for pair in pairs
    ):
        raise TransportPreviewError("transport A/B determinism audit failed")
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
            "Store transport sensitivity under modeled GlobalDES contention"
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


def _metric(row: Mapping[str, Any], *path: str) -> int:
    value: object = row
    for key in path:
        if not isinstance(value, Mapping):
            raise TransportPreviewError(f"metric path is missing: {'/'.join(path)}")
        value = value.get(key)
    if type(value) is not int:
        raise TransportPreviewError(f"metric is not an integer: {'/'.join(path)}")
    return value


def _render(rows: Sequence[Mapping[str, Any]], output: Path) -> dict[str, Any]:
    repeat_a = [row for row in rows if row.get("repetition") == "A"]
    by_key: dict[tuple[str, str, str, int], Mapping[str, Any]] = {}
    for row in repeat_a:
        key = (
            str(row["variant_id"]),
            str(row["context_bucket"]),
            str(row["scenario"]),
            int(row["seed"]),
        )
        by_key[key] = row
    svg = _Svg()
    svg.text(44, 40, "Store transport sensitivity under modeled GlobalDES contention", "title")
    svg.text(
        44,
        66,
        "Matched Weka-shape workload · GPU_FAILURE · seeds 0/1 · A/B exact",
        "sub",
    )
    panels = ((44, 105, 390, 560), (465, 105, 390, 560), (886, 105, 390, 560))
    for panel_x, panel_y, panel_w, panel_h in panels:
        svg.rect(
            panel_x,
            panel_y,
            panel_w,
            panel_h,
            "#f8fafc",
            stroke="#cbd5e1",
            **{"stroke-width": "1"},
        )
    svg.text(62, 136, "A  Whole-workload WCT delta vs GDR (%)", "panel")
    svg.text(483, 136, "B  Network byte-time multiplier vs GDR", "panel")
    svg.text(904, 136, "C  Peak Host DRAM staging (GiB)", "panel")

    left, top, plot_w, plot_h = 82, 175, 320, 410
    wct_min, wct_max = -0.02, 0.08
    for tick in (-0.02, 0.0, 0.02, 0.04, 0.06, 0.08):
        grid_y = top + plot_h - (tick - wct_min) / (wct_max - wct_min) * plot_h
        svg.line(
            left,
            grid_y,
            left + plot_w,
            grid_y,
            stroke="#94a3b8" if tick == 0 else "#e2e8f0",
            **{"stroke-width": "1.5" if tick == 0 else "1"},
        )
        svg.text(left - 35, grid_y + 4, f"{tick:.2f}", "tick")
    staged = TRANSPORTS[1:]
    wct_points: dict[str, list[tuple[float, float]]] = defaultdict(list)
    network_points: dict[str, list[tuple[float, float]]] = defaultdict(list)
    aggregate_bindings: list[dict[str, Any]] = []
    for bucket_index, bucket in enumerate(BUCKETS):
        x_a = left + bucket_index * plot_w / (len(BUCKETS) - 1)
        svg.text(x_a - 10, top + plot_h + 22, bucket, "tick")
        for transport in staged:
            selected_rows = [
                by_key[(transport, bucket, "gpu_failure", seed)] for seed in (0, 1)
            ]
            deltas = []
            multipliers = []
            for seed, row in zip((0, 1), selected_rows, strict=True):
                baseline = by_key[(TRANSPORTS[0], bucket, "gpu_failure", seed)]
                wct = _metric(row, "payload", "metrics", "workflow_completion_time_ns", "mean")
                gdr_wct = _metric(
                    baseline,
                    "payload",
                    "metrics",
                    "workflow_completion_time_ns",
                    "mean",
                )
                deltas.append(100.0 * (wct - gdr_wct) / gdr_wct)
                network_map = cast(
                    Mapping[str, int],
                    row["payload"]["metrics"]["resource_cost"]["network_byte_ns"],
                )
                gdr_network_map = cast(
                    Mapping[str, int],
                    baseline["payload"]["metrics"]["resource_cost"][
                        "network_byte_ns"
                    ],
                )
                network = sum(network_map.values())
                gdr_network = sum(gdr_network_map.values())
                multipliers.append(network / gdr_network)
            delta_mean = sum(deltas) / len(deltas)
            y_a = top + plot_h - (delta_mean - wct_min) / (wct_max - wct_min) * plot_h
            y_min = top + plot_h - (min(deltas) - wct_min) / (
                wct_max - wct_min
            ) * plot_h
            y_max = top + plot_h - (max(deltas) - wct_min) / (
                wct_max - wct_min
            ) * plot_h
            svg.line(x_a, y_min, x_a, y_max, stroke=COLORS[transport], **{"stroke-width": "2"})
            svg.point(
                x_a,
                y_a,
                color=COLORS[transport],
                point_id=f"wct:{transport}:{bucket}",
                rows=selected_rows,
            )
            wct_points[transport].append((x_a, y_a))

            left_b = 503
            x_b = left_b + bucket_index * plot_w / (len(BUCKETS) - 1)
            multiplier_mean = sum(multipliers) / len(multipliers)
            y_b = top + plot_h - (multiplier_mean - 1.0) / 2.2 * plot_h
            y_b_min = top + plot_h - (min(multipliers) - 1.0) / 2.2 * plot_h
            y_b_max = top + plot_h - (max(multipliers) - 1.0) / 2.2 * plot_h
            svg.line(x_b, y_b_min, x_b, y_b_max, stroke=COLORS[transport], **{"stroke-width": "2"})
            svg.point(
                x_b,
                y_b,
                color=COLORS[transport],
                point_id=f"network:{transport}:{bucket}",
                rows=selected_rows,
            )
            network_points[transport].append((x_b, y_b))
            aggregate_bindings.append(
                {
                    "transport": transport,
                    "context_bucket": bucket,
                    "scenario": "gpu_failure",
                    "run_ids": [str(row["run_id"]) for row in selected_rows],
                    "payload_sha256": [str(row["payload_sha256"]) for row in selected_rows],
                    "wct_delta_percent_mean": delta_mean,
                    "wct_delta_percent_seed_range": [min(deltas), max(deltas)],
                    "network_byte_time_multiplier_mean": multiplier_mean,
                    "network_byte_time_multiplier_seed_range": [
                        min(multipliers),
                        max(multipliers),
                    ],
                }
            )
    for transport in staged:
        for points in (wct_points[transport], network_points[transport]):
            for first, second in pairwise(points):
                svg.line(
                    first[0],
                    first[1],
                    second[0],
                    second[1],
                    stroke=COLORS[transport],
                    **{"stroke-width": "2"},
                )
    for tick in (1.0, 1.5, 2.0, 2.5, 3.0):
        network_tick_y = top + plot_h - (tick - 1.0) / 2.2 * plot_h
        svg.line(
            503,
            network_tick_y,
            503 + plot_w,
            network_tick_y,
            stroke="#e2e8f0",
            **{"stroke-width": "1"},
        )
        svg.text(468, network_tick_y + 4, f"{tick:.1f}x", "tick")
    for bucket_index, bucket in enumerate(BUCKETS):
        svg.text(493 + bucket_index * plot_w / 4, top + plot_h + 22, bucket, "tick")

    bar_left, bar_top, bar_w, bar_h = 930, 175, 300, 410
    for tick in (0.0, 0.3, 0.6, 0.9, 1.2):
        host_tick_y = bar_top + bar_h - tick / 1.2 * bar_h
        svg.line(
            bar_left,
            host_tick_y,
            bar_left + bar_w,
            host_tick_y,
            stroke="#e2e8f0",
            **{"stroke-width": "1"},
        )
        svg.text(bar_left - 35, host_tick_y + 4, f"{tick:.1f}", "tick")
    host_bindings = []
    for index, transport in enumerate(TRANSPORTS):
        selected_rows = [
            by_key[(transport, "128k", "gpu_failure", seed)] for seed in (0, 1)
        ]
        peaks = [
            _metric(
                row,
                "payload",
                "metrics",
                "resource_cost",
                "host_dram_staging_peak_bytes",
            )
            / 1024**3
            for row in selected_rows
        ]
        peak = max(peaks)
        x = bar_left + 28 + index * 96
        height = peak / 1.2 * bar_h
        svg.rect(x, bar_top + bar_h - height, 56, height, COLORS[transport], rx="4")
        svg.text(x - 5, bar_top + bar_h + 22, LABELS[transport].replace(" ", "\u00a0"), "tick")
        svg.text(x + 8, bar_top + bar_h - height - 8, f"{peak:.3f}", "label")
        host_bindings.append(
            {
                "transport": transport,
                "context_bucket": "128k",
                "scenario": "gpu_failure",
                "run_ids": [str(row["run_id"]) for row in selected_rows],
                "payload_sha256": [str(row["payload_sha256"]) for row in selected_rows],
                "peak_host_staging_gib": peak,
            }
        )
    legend_y = 630
    for index, transport in enumerate(staged):
        x = 78 + index * 190
        svg.rect(x, legend_y - 10, 16, 8, COLORS[transport])
        svg.text(x + 23, legend_y, LABELS[transport], "tick")
    svg.text(902, 620, "Modeled rates (assumed):", "sub")
    svg.text(902, 642, "RDMA Store 25 · Host 16 · TCP Store 8 GB/s", "sub")
    svg.text(44, 732, EVIDENCE_FOOTER, "footer")
    svg.text(
        44,
        758,
        "Whiskers show the seed-0/1 range; repeat B is determinism replay, not a sample.",
        "sub",
    )
    svg.write(output)
    return {
        "aggregate_bindings": aggregate_bindings,
        "host_staging_bindings": host_bindings,
        "interpretation": {
            "wct_direction": "positive_is_slower_than_rdma_gdr",
            "network_multiplier_baseline": "RDMA_GDR_same_bucket_scenario_seed",
            "seed_count": 2,
            "repeat_b_used_as_sample": False,
            "physical_timing_claim_allowed": False,
        },
    }


def generate_transport_preview(
    *, matrix_dir: Path, output_dir: Path, generator_source: Path
) -> TransportPreviewResult:
    if output_dir.exists():
        raise TransportPreviewError(f"existing figure output is forbidden: {output_dir}")
    matrix_manifest, rows = _verify_matrix(matrix_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.staging-", dir=output_dir.parent)
    )
    try:
        figure_path = staging / "f17-store-transport-sensitivity.svg"
        bindings = _render(rows, figure_path)
        document: dict[str, Any] = {
            "schema": "moonkvsim.aegiskv.transport_preview_manifest.v1",
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
                "id": "F17",
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
        return TransportPreviewResult(
            output_dir=output_dir,
            manifest_path=output_dir / "manifest.json",
            figure_path=output_dir / figure_path.name,
            manifest_sha256=_sha256_file(output_dir / "manifest.json"),
        )
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def audit_transport_preview(
    *, matrix_dir: Path, figure_dir: Path
) -> TransportPreviewAudit:
    matrix_manifest, _rows = _verify_matrix(matrix_dir)
    figure_manifest = _json_object(figure_dir / "manifest.json")
    if figure_manifest.get("status") != "PASS":
        raise TransportPreviewError("transport figure manifest is not passing")
    source = figure_manifest.get("source_matrix")
    if not isinstance(source, Mapping) or source.get("manifest_fingerprint") != matrix_manifest.get(
        "fingerprint"
    ):
        raise TransportPreviewError("transport figure source binding drifted")
    figure = figure_manifest.get("figure")
    if not isinstance(figure, Mapping) or figure.get("id") != "F17":
        raise TransportPreviewError("transport figure entry is malformed")
    figure_path = figure_dir / str(figure.get("path"))
    if _sha256_file(figure_path) != figure.get("sha256"):
        raise TransportPreviewError("transport figure SHA-256 drifted")
    root = ET.parse(figure_path).getroot()
    text = " ".join("" if item.text is None else item.text for item in root.iter())
    if EVIDENCE_FOOTER not in text:
        raise TransportPreviewError("transport figure lost its evidence footer")
    if not root.findall(".//{http://www.w3.org/2000/svg}g"):
        raise TransportPreviewError("transport figure has no result-bound points")
    return TransportPreviewAudit(
        status="PASS",
        matrix_manifest_fingerprint=str(matrix_manifest["fingerprint"]),
        result_count=int(matrix_manifest["result_count"]),
        pair_count=int(matrix_manifest["pair_count"]),
        figure_count=1,
        figure_manifest_sha256=_sha256_file(figure_dir / "manifest.json"),
        physical_execution=False,
        slurm_used=False,
    )
