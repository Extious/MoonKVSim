"""Reconstruct recorded node availability from the public InfiniteHBD trace.

No GPU jobs are launched. Nodes, not individual GPU faults or idle capacity,
are counted. All released event categories and timestamps are retained.
"""
from pathlib import Path
from collections import Counter, defaultdict, deque
import argparse
import csv
import hashlib
import json
import os
import shutil

os.environ.setdefault("MPLCONFIGDIR", "/tmp/aegiskv-gpu-availability-mpl")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import fitz
from design_plot_typography import configure

BASE = Path(__file__).resolve().parents[3]
DATA = BASE / "experiments/data/background-infinitehbd"
FLEET = 400  # Official release README; not the 231 nodes with fault events.


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reconstruct():
    source = json.loads((DATA / "SOURCE.json").read_text())
    for name, metadata in source["files"].items():
        assert digest(DATA / name) == metadata["sha256"], name
    events = json.loads((DATA / "fault_trace.json").read_text())
    assert all(a["event_time"] <= b["event_time"]
               for a, b in zip(events, events[1:]))
    pending = defaultdict(deque)
    pairs = []
    for index, event in enumerate(events):
        category = tuple(event["fault_type"][k] for k in ("Level", "Class", "Desc"))
        key = (event["node_id"], category)
        if event["event_type"] == "fault_start":
            pending[key].append((index, event["event_time"]))
        else:
            assert event["event_type"] == "fault_end" and pending[key], event
            start_index, start = pending[key].popleft()
            end = event["event_time"]
            assert end >= start
            pairs.append(dict(node_id=key[0], start=start, end=end,
                              level=category[0], fault_class=category[1],
                              description=category[2], start_row=start_index,
                              end_row=index))
    assert not any(pending.values())
    by_node = defaultdict(list)
    for pair in pairs:
        by_node[pair["node_id"]].append(pair)
    union = []
    merged_boundaries = 0
    for node, rows in sorted(by_node.items()):
        merged = []
        for row in sorted(rows, key=lambda x: (x["start"], x["end"])):
            if row["start"] == row["end"]:
                continue  # Keep in the paired table; zero duration adds no downtime.
            if merged and row["start"] <= merged[-1]["end"]:
                merged[-1]["end"] = max(merged[-1]["end"], row["end"])
                merged[-1]["source_rows"].append(row["start_row"])
                merged_boundaries += 1
            else:
                merged.append(dict(node_id=node, start=row["start"],
                                   end=row["end"], source_rows=[row["start_row"]]))
        union.extend(merged)
    delta = Counter()
    for row in union:
        delta[row["start"]] += 1
        delta[row["end"]] -= 1
    curve = [dict(time_days=0.0, unavailable=0, available=FLEET)]
    down = 0
    for time, change in sorted(delta.items()):
        down += change
        assert 0 <= down <= FLEET
        curve.append(dict(time_days=time, unavailable=down, available=FLEET-down))
    assert down == 0
    # Independent interval-membership check, including simultaneous events.
    for row in curve:
        direct = sum(x["start"] <= row["time_days"] < x["end"] for x in union)
        assert direct == row["unavailable"]
    area = sum((b["time_days"]-a["time_days"])*a["unavailable"]
               for a, b in zip(curve, curve[1:]))
    assert abs(area-sum(x["end"]-x["start"] for x in union)) < 1e-8
    summary = dict(
        source=source, fleet_gpu_servers=FLEET, affected_servers=len(by_node),
        event_rows=len(events), paired_fault_records=len(pairs),
        zero_duration_pairs=sum(x["start"] == x["end"] for x in pairs),
        merged_boundaries=merged_boundaries, positive_node_intervals=len(union),
        window_days=[0.0, curve[-1]["time_days"]],
        first_event_day=events[0]["event_time"],
        minimum_available=min(x["available"] for x in curve),
        maximum_unavailable=max(x["unavailable"] for x in curve),
        time_weighted_available=FLEET-area/curve[-1]["time_days"],
        fault_categories=dict(Counter(x["level"] for x in pairs)),
        evidence="Reconstruction from recorded production-training node fault intervals",
        definition="400 minus distinct nodes in the union of active recorded fault intervals",
        interval_convention="[start,end); pair by node and full fault category, then union by node",
        scope="All released categories, including tests/changes/unknown causes; not hardware-only",
        exposure="Fixed 400-node cohort from README; no active recorded fault at day 0",
        time_origin="Unchanged event_time in days; no calendar date or time rescaling inferred",
        limitations=["Not idle GPU counts or per-device health",
                     "Not a serving outage rate or end-to-end inference availability",
                     "No unrecorded outages or deployment membership changes inferred",
                     "README says 348 days; last released timestamp is day 348.9798"],
    )
    return curve, pairs, union, summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    curve, pairs, union, summary = reconstruct()
    for name, rows in [("availability.csv", curve), ("paired-events.csv", pairs),
                       ("node-intervals.csv", union)]:
        with (out/name).open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    summary["typography"] = configure()
    plt.rcParams.update({"axes.linewidth": .65, "pdf.fonttype": 42,
                         "svg.fonttype": "none"})
    fig, ax = plt.subplots(figsize=(3.33465, 1.85))
    fig.subplots_adjust(left=.205, right=.978, bottom=.27, top=.955)
    ax.axhline(FLEET, color="#888888", linewidth=.7, linestyle=(0, (3, 3)))
    ax.step([r["time_days"] for r in curve], [r["available"] for r in curve],
            where="post", color="#315F82", linewidth=1.0)
    ax.set_xlim(0, curve[-1]["time_days"])
    ax.set_ylim(360, 403)
    ax.set_xticks([0, 100, 200, 300])
    ax.set_yticks([360, 380, 400])
    ax.set_xlabel("Trace time (days)", labelpad=3)
    ax.set_ylabel("Available GPU servers", labelpad=3)
    ax.tick_params(length=2.2, pad=2)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#E2E6E9", linewidth=.5)
    ax.set_axisbelow(True)
    stem = out / "gpu-server-availability"
    for ext in ("pdf", "svg"):
        fig.savefig(stem.with_suffix("."+ext), facecolor="white")
    plt.close(fig)
    with fitz.open(stem.with_suffix(".pdf")) as doc:
        page = doc[0]
        for suffix, scale, space in [(".png", 3, fitz.csRGB),
                                     ("-gray.png", 3, fitz.csGRAY),
                                     ("-reading-size.png", 4/3, fitz.csRGB)]:
            page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=space,
                            alpha=False).save(out/(stem.name+suffix))
        spans = [s for b in page.get_text("dict")["blocks"] if "lines" in b
                 for l in b["lines"] for s in l["spans"] if s["text"].strip()]
        assert all(page.rect.contains(fitz.Rect(s["bbox"])) for s in spans)
        summary["geometry"] = dict(width_pt=page.rect.width, height_pt=page.rect.height,
                                   minimum_font_pt=min(s["size"] for s in spans))
        assert summary["geometry"]["minimum_font_pt"] >= 10
    summary["generator_sha256"] = digest(__file__)
    (out/"SUMMARY.json").write_text(json.dumps(summary, indent=2)+"\n")
    if args.publish:
        shutil.copy2(stem.with_suffix(".pdf"), BASE/"paper/figures"/stem.with_suffix(".pdf").name)
        shutil.copy2(stem.with_suffix(".png"), BASE/"paper/figures/preview"/stem.with_suffix(".png").name)
    print(json.dumps({k: summary[k] for k in ["paired_fault_records", "affected_servers",
          "zero_duration_pairs", "merged_boundaries", "minimum_available",
          "time_weighted_available", "geometry"]}, indent=2))


if __name__ == "__main__":
    main()
