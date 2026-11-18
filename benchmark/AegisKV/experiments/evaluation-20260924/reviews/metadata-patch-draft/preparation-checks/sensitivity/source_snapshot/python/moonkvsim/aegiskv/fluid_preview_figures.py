"""Render focused paper-preview SVGs for the AegisKV fluid-core E2 bundle.

The renderer is deliberately offline: it consumes a completed core matrix and
its representative GlobalDES journal projection.  It never executes a
simulator, physical runtime, CUDA, network operation, or Slurm job.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from moonkvsim.aegiskv.experiment_suite import EXPECTED_VARIANT_IDS

EVIDENCE_FOOTER: Final = (
    "E2 modeled/preliminary · GlobalDES only · not calibrated · no physical experiment"
)
EXPECTED_EVIDENCE: Final[dict[str, Any]] = {
    "class": "E2",
    "scope": "modeled/preliminary",
    "calibration": "not_calibrated",
    "physical_execution": False,
    "physical_timing_claim_allowed": False,
    "formal_use_allowed": False,
    "paper_ready": False,
    "slurm_used": False,
}
BUCKETS: Final = ("8k", "32k", "64k", "96k", "128k")
SCENARIOS: Final = ("no_failure", "gpu_failure")
REPETITIONS: Final = ("A", "B")
WIDTH: Final = 1280
HEIGHT: Final = 820
ACCOUNT_GROUPS: Final[tuple[tuple[str, tuple[str, ...], str], ...]] = (
    ("weights + runtime", ("MODEL_WEIGHTS", "RUNTIME_FIXED", "RUNTIME_DYNAMIC"), "#334155"),
    ("active primary KV", ("ACTIVE_PRIMARY_KV",), "#16a34a"),
    (
        "Peer-HBM committed/pending",
        ("PEER_PROTECTION_KV", "PEER_PROTECTION_PENDING"),
        "#7c3aed",
    ),
    ("recovery reserve", ("RECOVERY_DEST_RESERVED",), "#f59e0b"),
    ("transfer staging", ("TRANSFER_STAGING",), "#dc2626"),
    (
        "other attributed",
        (
            "INACTIVE_REUSABLE_KV",
            "ALLOCATOR_FRAGMENTATION",
            "UNATTRIBUTED_RESERVE",
        ),
        "#0891b2",
    ),
    ("free", ("FREE",), "#e2e8f0"),
    ("unavailable", ("UNAVAILABLE_CAPACITY",), "#111827"),
)
FLOW_COLORS: Final[dict[str, str]] = {
    "peer-fabric-rate": "#7c3aed",
    "store-fabric-rate": "#d97706",
    "gpu-hbm-max": "#059669",
}


class FluidPreviewError(ValueError):
    """A preview input or output violated the fail-closed contract."""


@dataclass(frozen=True, slots=True)
class FluidPreviewResult:
    output_dir: Path
    manifest_path: Path
    artifact_paths: tuple[Path, ...]
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class FluidPreviewAudit:
    status: str
    matrix_manifest_fingerprint: str
    matrix_result_count: int
    matrix_pair_count: int
    figure_count: int
    figure_manifest_sha256: str
    physical_execution: bool
    slurm_used: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "moonkvsim.aegiskv.fluid_preview_audit.v1",
            "status": self.status,
            "matrix_manifest_fingerprint": self.matrix_manifest_fingerprint,
            "matrix_result_count": self.matrix_result_count,
            "matrix_pair_count": self.matrix_pair_count,
            "figure_count": self.figure_count,
            "figure_manifest_sha256": self.figure_manifest_sha256,
            "physical_execution": self.physical_execution,
            "slurm_used": self.slurm_used,
        }


class _Svg:
    def __init__(self, title: str, subtitle: str) -> None:
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
        ET.SubElement(self.root, "title").text = title
        style = ET.SubElement(self.root, "style")
        style.text = (
            "text{font-family:DejaVu Sans,Arial,sans-serif;fill:#111827}"
            ".title{font-size:27px;font-weight:700}.subtitle{font-size:14px;fill:#475569}"
            ".label{font-size:14px;font-weight:650}.tick{font-size:11px;fill:#475569}"
            ".small{font-size:10px;fill:#475569}.footer{font-size:13px;font-weight:700;"
            "fill:#991b1b}.panel{font-size:15px;font-weight:700}"
        )
        self.rect(0, 0, WIDTH, HEIGHT, fill="#ffffff")
        self.text(48, 42, title, css="title")
        self.text(48, 68, subtitle, css="subtitle")

    def group(self, *, run_id: str, result_hash: str, point_id: str) -> ET.Element:
        group = ET.SubElement(
            self.root,
            "g",
            {
                "data-point-id": point_id,
                "data-run-id": run_id,
                "data-result-hash": result_hash,
            },
        )
        ET.SubElement(group, "title").text = f"{point_id} | {run_id} | {result_hash}"
        return group

    def rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        fill: str,
        stroke: str = "none",
        opacity: float = 1.0,
        parent: ET.Element | None = None,
    ) -> None:
        ET.SubElement(
            self.root if parent is None else parent,
            "rect",
            {
                "x": _fmt(x),
                "y": _fmt(y),
                "width": _fmt(max(0.0, width)),
                "height": _fmt(max(0.0, height)),
                "fill": fill,
                "stroke": stroke,
                "opacity": _fmt(opacity),
            },
        )

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        stroke: str = "#334155",
        width: float = 1.0,
        dash: str | None = None,
        parent: ET.Element | None = None,
    ) -> None:
        attributes = {
            "x1": _fmt(x1),
            "y1": _fmt(y1),
            "x2": _fmt(x2),
            "y2": _fmt(y2),
            "stroke": stroke,
            "stroke-width": _fmt(width),
        }
        if dash is not None:
            attributes["stroke-dasharray"] = dash
        ET.SubElement(self.root if parent is None else parent, "line", attributes)

    def polyline(
        self,
        points: Sequence[tuple[float, float]],
        *,
        stroke: str,
        width: float = 2.0,
        parent: ET.Element | None = None,
    ) -> None:
        ET.SubElement(
            self.root if parent is None else parent,
            "polyline",
            {
                "points": " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in points),
                "fill": "none",
                "stroke": stroke,
                "stroke-width": _fmt(width),
                "stroke-linejoin": "round",
            },
        )

    def text(
        self,
        x: float,
        y: float,
        value: str,
        *,
        css: str = "tick",
        anchor: str = "start",
        parent: ET.Element | None = None,
        rotate: float | None = None,
    ) -> None:
        attributes = {
            "x": _fmt(x),
            "y": _fmt(y),
            "class": css,
            "text-anchor": anchor,
        }
        if rotate is not None:
            attributes["transform"] = f"rotate({_fmt(rotate)} {_fmt(x)} {_fmt(y)})"
        element = ET.SubElement(
            self.root if parent is None else parent,
            "text",
            attributes,
        )
        element.text = value

    def serialize(self) -> bytes:
        self.line(48, 776, 1232, 776, stroke="#fecaca")
        self.text(640, 806, EVIDENCE_FOOTER, css="footer", anchor="middle")
        ET.indent(self.root, space="  ")
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            + ET.tostring(self.root, encoding="unicode", short_empty_elements=True)
            + "\n"
        ).encode()


def _fmt(value: float) -> str:
    if not math.isfinite(value):
        raise FluidPreviewError("non-finite SVG coordinate")
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _scale(value: float, lower: float, upper: float, out_lower: float, out_upper: float) -> float:
    if upper <= lower:
        return (out_lower + out_upper) / 2
    return out_lower + (value - lower) * (out_upper - out_lower) / (upper - lower)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()


def _json_fingerprint(value: object) -> str:
    return _sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    )


def _load_regular(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise FluidPreviewError(f"required regular input is missing: {path}")
    return path.read_bytes()


def _object(value: object, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FluidPreviewError(f"{location} must be an object")
    return value


def _array(value: object, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise FluidPreviewError(f"{location} must be an array")
    return value


def _integer(value: object, location: str) -> int:
    if type(value) is not int or value < 0:
        raise FluidPreviewError(f"{location} must be a non-negative integer")
    return value


def _number(value: object, location: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise FluidPreviewError(f"{location} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise FluidPreviewError(f"{location} must be finite")
    return result


def _validate_inputs(
    matrix_dir: Path,
) -> tuple[
    dict[str, Any],
    tuple[dict[str, Any], ...],
    dict[str, Any],
    dict[str, str],
]:
    paths = {
        name: matrix_dir / name
        for name in ("manifest.json", "results.jsonl", "representative-run.json")
    }
    raw = {name: _load_regular(path) for name, path in paths.items()}
    try:
        manifest = _object(json.loads(raw["manifest.json"]), "manifest")
        representative = _object(
            json.loads(raw["representative-run.json"]), "representative"
        )
        rows = tuple(
            _object(json.loads(line), f"results line {index}")
            for index, line in enumerate(raw["results.jsonl"].splitlines(), start=1)
            if line
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise FluidPreviewError("preview inputs contain invalid JSON") from error
    if (
        manifest.get("status") != "PASS"
        or manifest.get("schema") != "moonkvsim.aegiskv.e2_matrix_suite.v1.manifest"
        or manifest.get("result_count") != len(rows)
    ):
        raise FluidPreviewError("matrix manifest status, schema, or result count is invalid")
    manifest_payload = dict(manifest)
    declared_fingerprint = manifest_payload.pop("fingerprint", None)
    if (
        not isinstance(declared_fingerprint, str)
        or _json_fingerprint(manifest_payload) != declared_fingerprint
    ):
        raise FluidPreviewError("matrix manifest fingerprint mismatch")
    evidence = _object(manifest.get("evidence"), "manifest.evidence")
    if evidence != EXPECTED_EVIDENCE:
        raise FluidPreviewError("matrix evidence boundary drifted")
    seeds: set[int] = set()
    cells: set[tuple[str, str, str, int, str]] = set()
    row_hashes: dict[str, str] = {}
    pairs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("suite") != "core" or row.get("status") != "PASS":
            raise FluidPreviewError("fluid preview requires a PASS core-only matrix")
        run_id = row.get("run_id")
        payload_hash = row.get("payload_sha256")
        variant_id = row.get("variant_id")
        bucket = row.get("context_bucket")
        scenario = row.get("scenario")
        repetition = row.get("repetition")
        seed = row.get("seed")
        if (
            not isinstance(run_id, str)
            or not isinstance(payload_hash, str)
            or variant_id not in EXPECTED_VARIANT_IDS["core"]
            or bucket not in BUCKETS
            or scenario not in SCENARIOS
            or repetition not in REPETITIONS
            or type(seed) is not int
        ):
            raise FluidPreviewError("result row identity is invalid")
        payload = _object(row.get("payload"), f"{run_id}.payload")
        if _json_fingerprint(payload) != payload_hash:
            raise FluidPreviewError(f"{run_id} payload hash mismatch")
        resource_model = _object(payload.get("resource_model"), f"{run_id}.resource_model")
        if (
            resource_model.get("communication_backend") != "flow_contention"
            or resource_model.get("flow_clock") != "shared_global_des_now_ns"
            or _object(row.get("evidence"), f"{run_id}.evidence") != EXPECTED_EVIDENCE
        ):
            raise FluidPreviewError("result row is not a fluid GlobalDES E2 result")
        if run_id in row_hashes:
            raise FluidPreviewError("duplicate run_id")
        row_hashes[run_id] = payload_hash
        pair_id = row.get("pair_id")
        if not isinstance(pair_id, str):
            raise FluidPreviewError("result row pair_id is invalid")
        pairs[pair_id].append(row)
        seeds.add(seed)
        cells.add((cast(str, variant_id), cast(str, bucket), cast(str, scenario), seed, repetition))
    if len(seeds) < 2:
        raise FluidPreviewError("fluid preview requires at least two seeds")
    expected_cells = {
        (variant, bucket, scenario, seed, repetition)
        for variant in EXPECTED_VARIANT_IDS["core"]
        for bucket in BUCKETS
        for scenario in SCENARIOS
        for seed in seeds
        for repetition in REPETITIONS
    }
    if cells != expected_cells:
        raise FluidPreviewError("core preview matrix is incomplete")
    if manifest.get("pair_count") != len(pairs) or len(rows) != 2 * len(pairs):
        raise FluidPreviewError("matrix pair count is invalid")
    for pair_id, pair_rows in pairs.items():
        if (
            len(pair_rows) != 2
            or {row.get("repetition") for row in pair_rows} != set(REPETITIONS)
            or len({row.get("payload_sha256") for row in pair_rows}) != 1
            or len({row.get("journal_sha256") for row in pair_rows}) != 1
        ):
            raise FluidPreviewError(f"{pair_id} A/B determinism binding failed")
    run_id = representative.get("run_id")
    result_hash = representative.get("payload_sha256")
    if (
        not isinstance(run_id, str)
        or not isinstance(result_hash, str)
        or row_hashes.get(run_id) != result_hash
        or representative.get("status") != "PASS"
    ):
        raise FluidPreviewError("representative row binding is invalid")
    hashes = {name: _sha256(value) for name, value in raw.items()}
    artifact_hashes = _object(manifest.get("artifact_hashes"), "artifact_hashes")
    for name in ("results.jsonl", "representative-run.json"):
        binding = _object(artifact_hashes.get(name), f"artifact_hashes.{name}")
        if (
            binding.get("sha256") != hashes[name]
            or binding.get("size_bytes") != len(raw[name])
        ):
            raise FluidPreviewError(f"matrix artifact hash or size mismatch: {name}")
    return manifest, rows, representative, hashes


def _account_value(accounts: Mapping[str, Any], names: Sequence[str]) -> int:
    total = 0
    for name in names:
        total += _integer(accounts.get(name), f"accounts.{name}")
    return total


def _render_hbm_stack(representative: Mapping[str, Any]) -> bytes:
    data = _object(representative.get("representative"), "representative.data")
    timelines = _object(data.get("gpu_hbm_timelines"), "gpu_hbm_timelines")
    run_id = cast(str, representative["run_id"])
    result_hash = cast(str, representative["payload_sha256"])
    canvas = _Svg(
        "Full per-GPU HBM account stacks on one virtual clock",
        "Equal-width event-boundary sequence; four physical GPUs; 128K GPU_FAILURE representative",
    )
    group = canvas.group(run_id=run_id, result_hash=result_hash, point_id="hbm-stack")
    for legend_index, (label, _accounts, color) in enumerate(ACCOUNT_GROUPS):
        legend_row, legend_column = divmod(legend_index, 4)
        legend_x = 52 + legend_column * 300
        legend_y = 84 + legend_row * 22
        canvas.rect(legend_x, legend_y, 13, 10, fill=color, parent=group)
        canvas.text(legend_x + 18, legend_y + 10, label, css="small", parent=group)
    gpu_ids = sorted(timelines)
    if not gpu_ids:
        raise FluidPreviewError("representative has no GPU HBM timelines")
    panel_width = 550
    panel_height = 250
    for index, gpu_id in enumerate(gpu_ids):
        row, column = divmod(index, 2)
        left = 55 + column * 615
        top = 138 + row * 285
        right = left + panel_width
        bottom = top + panel_height - 36
        snapshots = [
            _object(item, f"{gpu_id}.snapshot")
            for item in _array(timelines[gpu_id], f"{gpu_id}.timeline")
        ]
        capacity = _integer(snapshots[0].get("capacity_bytes"), "snapshot.capacity_bytes")
        canvas.text(left, top - 8, gpu_id, css="panel", parent=group)
        canvas.rect(
            left,
            top,
            panel_width,
            bottom - top,
            fill="#ffffff",
            stroke="#cbd5e1",
            parent=group,
        )
        for snapshot_index, snapshot in enumerate(snapshots):
            _integer(snapshot.get("timestamp_ns"), "snapshot.timestamp_ns")
            x1 = _scale(snapshot_index, 0, len(snapshots), left, right)
            x2 = _scale(snapshot_index + 1, 0, len(snapshots), left, right)
            accounts = _object(snapshot.get("accounts"), "snapshot.accounts")
            cursor = float(bottom)
            accounted = 0
            for _label, account_names, color in ACCOUNT_GROUPS:
                value = _account_value(accounts, account_names)
                accounted += value
                height = (bottom - top) * value / capacity
                cursor -= height
                canvas.rect(
                    x1,
                    cursor,
                    max(0.7, x2 - x1),
                    height,
                    fill=color,
                    parent=group,
                )
            if accounted != capacity:
                raise FluidPreviewError(f"{gpu_id} snapshot does not conserve HBM")
        canvas.text(left - 6, top + 4, f"{capacity / 1024**3:.0f} GiB", anchor="end", parent=group)
        canvas.text(left - 6, bottom + 4, "0", anchor="end", parent=group)
        canvas.text(left, bottom + 18, "event 0", css="small", parent=group)
        canvas.text(
            right,
            bottom + 18,
            f"event {len(snapshots) - 1}",
            css="small",
            anchor="end",
            parent=group,
        )
    return canvas.serialize()


def _binned_flow_utilization(
    intervals: Sequence[Mapping[str, Any]],
    capacities: Mapping[str, Any],
    *,
    bins: int = 180,
) -> tuple[int, int, int, dict[str, list[float]]]:
    lower_ns = min(_integer(item.get("start_ns"), "flow.start_ns") for item in intervals)
    upper_ns = max(_integer(item.get("end_ns"), "flow.end_ns") for item in intervals)
    if upper_ns <= lower_ns:
        raise FluidPreviewError("flow interval window is empty")
    series = {
        "peer-fabric-rate": [0.0] * bins,
        "store-fabric-rate": [0.0] * bins,
        "gpu-hbm-max": [0.0] * bins,
    }
    gpu_by_bin: dict[str, list[float]] = {
        resource_id: [0.0] * bins
        for resource_id in capacities
        if resource_id.endswith(".hbm-rate")
    }
    by_epoch: dict[tuple[int, int], list[Mapping[str, Any]]] = defaultdict(list)
    for item in intervals:
        epoch = (
            _integer(item.get("start_ns"), "flow.start_ns"),
            _integer(item.get("end_ns"), "flow.end_ns"),
        )
        by_epoch[epoch].append(item)
    epochs = sorted(by_epoch.items())
    active_duration_ns = sum(end_ns - start_ns for (start_ns, end_ns), _ in epochs)
    if active_duration_ns <= 0:
        raise FluidPreviewError("fluid preview has no positive active epoch")
    bin_width = active_duration_ns / bins
    active_cursor = 0.0
    for (start_ns, end_ns), epoch_items in epochs:
        duration_ns = end_ns - start_ns
        epoch_rates: dict[str, float] = defaultdict(float)
        for item in epoch_items:
            rate = _number(item.get("allocated_rate_bytes_per_second"), "flow.rate")
            path = _array(item.get("path_resource_ids"), "flow.path_resource_ids")
            for resource_id_value in path:
                if not isinstance(resource_id_value, str) or resource_id_value not in capacities:
                    raise FluidPreviewError("flow path references an unknown rate resource")
                capacity = _number(capacities[resource_id_value], "rate capacity")
                epoch_rates[resource_id_value] += rate / capacity
        first = max(0, min(bins - 1, int(active_cursor / bin_width)))
        last = max(
            0,
            min(bins - 1, int(max(active_cursor, active_cursor + duration_ns - 1) / bin_width)),
        )
        for bin_index in range(first, last + 1):
            bin_start = bin_index * bin_width
            bin_end = bin_start + bin_width
            overlap = max(
                0.0,
                min(active_cursor + duration_ns, bin_end) - max(active_cursor, bin_start),
            )
            for resource_id, utilization in epoch_rates.items():
                target = (
                    series[resource_id]
                    if resource_id in {"peer-fabric-rate", "store-fabric-rate"}
                    else gpu_by_bin.get(resource_id)
                )
                if target is not None:
                    target[bin_index] += overlap / bin_width * utilization
        active_cursor += duration_ns
    for bin_index in range(bins):
        series["gpu-hbm-max"][bin_index] = max(
            (values[bin_index] for values in gpu_by_bin.values()),
            default=0.0,
        )
    if any(value > 1.000001 for values in series.values() for value in values):
        raise FluidPreviewError("binned flow utilization exceeds capacity")
    return lower_ns, upper_ns, active_duration_ns, series


def _render_flow_contention(representative: Mapping[str, Any]) -> bytes:
    data = _object(representative.get("representative"), "representative.data")
    intervals = tuple(
        _object(item, "flow interval")
        for item in _array(data.get("flow_rate_intervals"), "flow_rate_intervals")
    )
    payload = _object(representative.get("payload"), "representative.payload")
    resource_model = _object(payload.get("resource_model"), "resource_model")
    capacities = _object(resource_model.get("rate_resources"), "rate_resources")
    lower_ns, upper_ns, active_duration_ns, series = _binned_flow_utilization(
        intervals, capacities
    )
    run_id = cast(str, representative["run_id"])
    result_hash = cast(str, representative["payload_sha256"])
    canvas = _Svg(
        "Work-conserving fluid contention on the GlobalDES clock",
        "Weighted max-min shares; idle gaps removed, active fluid epochs preserved",
    )
    group = canvas.group(run_id=run_id, result_hash=result_hash, point_id="fluid-utilization")
    left, right, top, bottom = 105.0, 1225.0, 120.0, 690.0
    for tick in range(6):
        y = bottom - (bottom - top) * tick / 5
        canvas.line(left, y, right, y, stroke="#e2e8f0", parent=group)
        canvas.text(left - 12, y + 4, f"{tick * 20}%", anchor="end", parent=group)
    canvas.line(left, top, left, bottom, width=1.4, parent=group)
    canvas.line(left, bottom, right, bottom, width=1.4, parent=group)
    bins = len(next(iter(series.values())))
    for label_index, (resource_id, values) in enumerate(series.items()):
        color = FLOW_COLORS[resource_id]
        points = [
            (
                _scale(index + 0.5, 0, bins, left, right),
                _scale(value, 0, 1, bottom, top),
            )
            for index, value in enumerate(values)
        ]
        canvas.polyline(points, stroke=color, width=2.2, parent=group)
        legend_x = 180 + label_index * 300
        canvas.line(legend_x, 94, legend_x + 30, 94, stroke=color, width=3, parent=group)
        canvas.text(legend_x + 38, 99, resource_id, css="label", parent=group)
    canvas.text(
        (left + right) / 2,
        732,
        "compressed active-flow time (idle gaps removed)",
        css="label",
        anchor="middle",
    )
    canvas.text(24, (top + bottom) / 2, "rate utilization", css="label", rotate=-90)
    canvas.text(left, bottom + 20, "0%", parent=group)
    canvas.text(right, bottom + 20, "100%", anchor="end", parent=group)
    canvas.text(
        right,
        top + 12,
        (
            f"{len(intervals)} rate intervals · {active_duration_ns / 1e9:.3f} active s · "
            f"{(upper_ns - lower_ns) / 1e9:.1f} wall-window s"
        ),
        css="small",
        anchor="end",
        parent=group,
    )
    return canvas.serialize()


def _step_points(
    snapshots: Sequence[Mapping[str, Any]],
    account: str,
    *,
    lower_ns: int,
    upper_ns: int,
    left: float,
    right: float,
    top: float,
    bottom: float,
    y_max: float,
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    prior_value = 0
    for snapshot in snapshots:
        timestamp = _integer(snapshot.get("timestamp_ns"), "snapshot.timestamp_ns")
        accounts = _object(snapshot.get("accounts"), "snapshot.accounts")
        value = _integer(accounts.get(account), f"accounts.{account}")
        if timestamp < lower_ns:
            prior_value = value
            continue
        if timestamp > upper_ns:
            break
        x = _scale(timestamp, lower_ns, upper_ns, left, right)
        prior_y = _scale(prior_value, 0, y_max, bottom, top)
        current_y = _scale(value, 0, y_max, bottom, top)
        if not points:
            points.append((left, prior_y))
        points.extend(((x, prior_y), (x, current_y)))
        prior_value = value
    points.append((right, _scale(prior_value, 0, y_max, bottom, top)))
    return points


def _render_recovery_hbm(representative: Mapping[str, Any]) -> bytes:
    data = _object(representative.get("representative"), "representative.data")
    recovery_events = [
        _object(item, "recovery event")
        for item in _array(data.get("recovery_events"), "recovery_events")
    ]
    plan = next((item for item in recovery_events if item.get("event") == "RECOVERY_PLAN"), None)
    activation = next(
        (item for item in recovery_events if item.get("event") == "RECOVERY_ATOMIC_ACTIVATION"),
        None,
    )
    failures = _array(data.get("failure_events"), "failure_events")
    if plan is None or activation is None or not failures:
        raise FluidPreviewError("representative lacks a complete recovery window")
    target_gpu = plan.get("target_gpu_id")
    if not isinstance(target_gpu, str):
        raise FluidPreviewError("recovery target GPU is invalid")
    lower_ns = _integer(_object(failures[0], "failure").get("timestamp_ns"), "failure time")
    upper_ns = _integer(activation.get("timestamp_ns"), "activation time")
    timelines = _object(data.get("gpu_hbm_timelines"), "gpu_hbm_timelines")
    snapshots = [
        _object(item, "recovery HBM snapshot")
        for item in _array(timelines.get(target_gpu), f"{target_gpu}.timeline")
    ]
    accounts = (
        ("RECOVERY_DEST_RESERVED", "#f59e0b"),
        ("TRANSFER_STAGING", "#dc2626"),
        ("ACTIVE_PRIMARY_KV", "#16a34a"),
        ("PEER_PROTECTION_KV", "#7c3aed"),
    )
    y_max = max(
        1,
        max(
            _integer(_object(item.get("accounts"), "snapshot.accounts").get(account), account)
            for item in snapshots
            for account, _color in accounts
        ),
    )
    run_id = cast(str, representative["run_id"])
    result_hash = cast(str, representative["payload_sha256"])
    canvas = _Svg(
        "Recovery destination reserve and KV materialization",
        f"{target_gpu}; relative to GPU failure; staging is zero when no replica is restorable",
    )
    group = canvas.group(run_id=run_id, result_hash=result_hash, point_id="recovery-hbm")
    left, right, top, bottom = 110.0, 1220.0, 155.0, 690.0
    for tick in range(6):
        y = bottom - (bottom - top) * tick / 5
        canvas.line(left, y, right, y, stroke="#e2e8f0", parent=group)
        canvas.text(
            left - 12,
            y + 4,
            f"{y_max / 1024**3 * tick / 5:.1f}",
            anchor="end",
            parent=group,
        )
    for index, (account, color) in enumerate(accounts):
        points = _step_points(
            snapshots,
            account,
            lower_ns=lower_ns,
            upper_ns=upper_ns,
            left=left,
            right=right,
            top=top,
            bottom=bottom,
            y_max=y_max,
        )
        canvas.polyline(points, stroke=color, width=2.5, parent=group)
        legend_x = 145 + index * 270
        canvas.line(legend_x, 95, legend_x + 28, 95, stroke=color, width=3, parent=group)
        canvas.text(legend_x + 36, 100, account, css="small", parent=group)
    marker_events = [
        ("FAILURE", lower_ns),
        *[
            (cast(str, event["event"]), cast(int, event["timestamp_ns"]))
            for event in recovery_events
            if event.get("event")
            in {
                "RECOVERY_PLAN",
                "PROMPT_SUFFIX_RECOMPUTE_START",
                "PROMPT_SUFFIX_RECOMPUTE_COMPLETE",
                "RECOVERY_ATOMIC_ACTIVATION",
            }
            and type(event.get("timestamp_ns")) is int
        ],
    ]
    canvas.text(
        left,
        137,
        " · ".join(
            f"{index + 1} {label.replace('_', ' ')}"
            for index, (label, _) in enumerate(marker_events)
        ),
        css="small",
        parent=group,
    )
    for marker_index, (_label, timestamp_value) in enumerate(marker_events):
        if lower_ns <= timestamp_value <= upper_ns:
            x = _scale(timestamp_value, lower_ns, upper_ns, left, right)
            canvas.line(x, top, x, bottom, stroke="#64748b", dash="4 3", parent=group)
            canvas.text(
                x,
                top - 7 - (marker_index % 2) * 12,
                str(marker_index + 1),
                css="small",
                anchor="middle",
                parent=group,
            )
    canvas.line(left, top, left, bottom, width=1.4, parent=group)
    canvas.line(left, bottom, right, bottom, width=1.4, parent=group)
    canvas.text(24, (top + bottom) / 2, "GiB", css="label", rotate=-90)
    canvas.text(
        (left + right) / 2,
        732,
        f"virtual time since failure (window {(upper_ns - lower_ns) / 1e9:.3f} s)",
        css="label",
        anchor="middle",
    )
    return canvas.serialize()


def generate_fluid_core_preview(
    *, matrix_dir: Path, output_dir: Path
) -> FluidPreviewResult:
    """Atomically publish three focused SVGs with source-bound provenance."""

    if output_dir.exists():
        raise FluidPreviewError(f"preview output already exists: {output_dir}")
    manifest, _rows, representative, input_hashes = _validate_inputs(matrix_dir)
    renderers = (
        ("F3V2", "full-gpu-hbm-account-stack", _render_hbm_stack),
        ("F5V2", "fluid-contention-utilization", _render_flow_contention),
        ("F16", "recovery-reserve-staging", _render_recovery_hbm),
    )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    artifact_paths: list[Path] = []
    entries: list[dict[str, Any]] = []
    try:
        for figure_id, slug, renderer in renderers:
            svg_name = f"{figure_id.lower()}-{slug}.svg"
            provenance_name = f"{figure_id.lower()}-{slug}.provenance.json"
            svg = renderer(representative)
            svg_sha256 = _sha256(svg)
            provenance = {
                "schema": "moonkvsim.aegiskv.fluid_preview_figure.v1",
                "figure_id": figure_id,
                "evidence": EXPECTED_EVIDENCE,
                "paper_ready": False,
                "matrix_manifest_fingerprint": manifest["fingerprint"],
                "input_sha256": input_hashes,
                "representative_binding": {
                    "run_id": representative["run_id"],
                    "payload_sha256": representative["payload_sha256"],
                },
                "svg": {"file": svg_name, "sha256": svg_sha256},
                "generator_source_sha256": _sha256(Path(__file__).read_bytes()),
                "physical_execution": False,
                "slurm_used": False,
            }
            provenance_bytes = _canonical_json(provenance)
            (staging / svg_name).write_bytes(svg)
            (staging / provenance_name).write_bytes(provenance_bytes)
            entries.append(
                {
                    "figure_id": figure_id,
                    "svg": {
                        "file": svg_name,
                        "sha256": svg_sha256,
                        "size_bytes": len(svg),
                    },
                    "provenance": {
                        "file": provenance_name,
                        "sha256": _sha256(provenance_bytes),
                        "size_bytes": len(provenance_bytes),
                    },
                }
            )
        preview_manifest: dict[str, Any] = {
            "schema": "moonkvsim.aegiskv.fluid_preview_set.v1",
            "status": "PASS",
            "evidence": EXPECTED_EVIDENCE,
            "matrix_manifest_fingerprint": manifest["fingerprint"],
            "input_sha256": input_hashes,
            "representative_run_id": representative["run_id"],
            "figure_count": len(entries),
            "figures": entries,
            "excluded_claims": [
                "physical_timing_accuracy",
                "calibrated_hardware_performance",
                "paper_ready_result",
            ],
        }
        preview_manifest["fingerprint"] = _sha256(_canonical_json(preview_manifest))
        manifest_bytes = _canonical_json(preview_manifest)
        (staging / "manifest.json").write_bytes(manifest_bytes)
        staging.replace(output_dir)
        artifact_paths = [
            output_dir / item[key]["file"]
            for item in entries
            for key in ("svg", "provenance")
        ]
        return FluidPreviewResult(
            output_dir=output_dir,
            manifest_path=output_dir / "manifest.json",
            artifact_paths=tuple(artifact_paths),
            manifest_sha256=_sha256(manifest_bytes),
        )
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def audit_fluid_core_preview(
    *, matrix_dir: Path, figure_dir: Path
) -> FluidPreviewAudit:
    """Re-read and verify every core-matrix preview artifact and binding."""

    matrix_manifest, _rows, representative, input_hashes = _validate_inputs(matrix_dir)
    manifest_path = figure_dir / "manifest.json"
    manifest_bytes = _load_regular(manifest_path)
    try:
        figure_manifest = _object(json.loads(manifest_bytes), "figure manifest")
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise FluidPreviewError("figure manifest is invalid JSON") from error
    fingerprint = figure_manifest.pop("fingerprint", None)
    if not isinstance(fingerprint, str) or fingerprint != _sha256(
        _canonical_json(figure_manifest)
    ):
        raise FluidPreviewError("figure manifest fingerprint mismatch")
    if (
        figure_manifest.get("schema") != "moonkvsim.aegiskv.fluid_preview_set.v1"
        or figure_manifest.get("status") != "PASS"
        or figure_manifest.get("evidence") != EXPECTED_EVIDENCE
        or figure_manifest.get("matrix_manifest_fingerprint")
        != matrix_manifest.get("fingerprint")
        or figure_manifest.get("input_sha256") != input_hashes
        or figure_manifest.get("representative_run_id") != representative.get("run_id")
    ):
        raise FluidPreviewError("figure manifest binding or evidence drifted")
    entries = [
        _object(item, "figure entry")
        for item in _array(figure_manifest.get("figures"), "figure manifest.figures")
    ]
    if len(entries) != 3 or figure_manifest.get("figure_count") != len(entries):
        raise FluidPreviewError("fluid preview must contain exactly three figures")
    expected_files = {"manifest.json"}
    expected_ids = {"F3V2", "F5V2", "F16"}
    actual_ids: set[str] = set()
    generator_hash = _sha256(Path(__file__).read_bytes())
    for entry in entries:
        figure_id = entry.get("figure_id")
        if not isinstance(figure_id, str):
            raise FluidPreviewError("figure ID is invalid")
        actual_ids.add(figure_id)
        svg_binding = _object(entry.get("svg"), f"{figure_id}.svg")
        provenance_binding = _object(
            entry.get("provenance"), f"{figure_id}.provenance"
        )
        for kind, binding in (
            ("svg", svg_binding),
            ("provenance", provenance_binding),
        ):
            file_name = binding.get("file")
            if (
                not isinstance(file_name, str)
                or Path(file_name).name != file_name
                or "/" in file_name
                or "\\" in file_name
            ):
                raise FluidPreviewError(f"{figure_id} {kind} path is unsafe")
            path = figure_dir / file_name
            content = _load_regular(path)
            if binding.get("sha256") != _sha256(content) or binding.get(
                "size_bytes"
            ) != len(content):
                raise FluidPreviewError(f"{figure_id} {kind} hash or size mismatch")
            expected_files.add(file_name)
        svg_bytes = _load_regular(figure_dir / cast(str, svg_binding["file"]))
        try:
            svg_root = ET.fromstring(svg_bytes)
        except ET.ParseError as error:
            raise FluidPreviewError(f"{figure_id} SVG is invalid XML") from error
        if not svg_root.tag.endswith("svg") or EVIDENCE_FOOTER.encode() not in svg_bytes:
            raise FluidPreviewError(f"{figure_id} SVG evidence footer is missing")
        if not svg_root.findall(".//*[@data-run-id]"):
            raise FluidPreviewError(f"{figure_id} SVG lacks a representative binding")
        provenance_bytes = _load_regular(
            figure_dir / cast(str, provenance_binding["file"])
        )
        try:
            provenance = _object(json.loads(provenance_bytes), f"{figure_id} provenance")
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise FluidPreviewError(f"{figure_id} provenance is invalid JSON") from error
        if (
            provenance.get("figure_id") != figure_id
            or provenance.get("evidence") != EXPECTED_EVIDENCE
            or provenance.get("input_sha256") != input_hashes
            or provenance.get("matrix_manifest_fingerprint")
            != matrix_manifest.get("fingerprint")
            or provenance.get("generator_source_sha256") != generator_hash
            or provenance.get("representative_binding")
            != {
                "run_id": representative["run_id"],
                "payload_sha256": representative["payload_sha256"],
            }
            or provenance.get("svg")
            != {"file": svg_binding["file"], "sha256": svg_binding["sha256"]}
            or provenance.get("physical_execution") is not False
            or provenance.get("slurm_used") is not False
        ):
            raise FluidPreviewError(f"{figure_id} provenance binding drifted")
    if actual_ids != expected_ids:
        raise FluidPreviewError("fluid preview figure IDs drifted")
    directory_entries = tuple(figure_dir.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in directory_entries):
        raise FluidPreviewError("figure directory must contain regular files only")
    actual_files = {path.name for path in directory_entries}
    if actual_files != expected_files:
        raise FluidPreviewError("figure directory contains missing or extra files")
    return FluidPreviewAudit(
        status="PASS",
        matrix_manifest_fingerprint=cast(str, matrix_manifest["fingerprint"]),
        matrix_result_count=_integer(matrix_manifest.get("result_count"), "result_count"),
        matrix_pair_count=_integer(matrix_manifest.get("pair_count"), "pair_count"),
        figure_count=len(entries),
        figure_manifest_sha256=_sha256(manifest_bytes),
        physical_execution=False,
        slurm_used=False,
    )
