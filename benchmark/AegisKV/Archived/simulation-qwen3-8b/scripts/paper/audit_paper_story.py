"""Check narrative figures against actual exports, paired data, and frozen runs."""

import argparse
import csv
import gzip
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont
from matplotlib.font_manager import findfont

from paper_paths import ROOT, DATA
from three_system_data import SYSTEMS, load_case, sha
from three_system_review_notes import controller_service

OUT = ROOT / "output/pdf/aegiskv-paper-story-20260908"
ART = ROOT / "output/paper-story-20260908"
DIRECTORY = ROOT / "benchmark/AegisKV/experiments"
RENDER = ROOT / "tmp/pdfs/paper-story-review"


def audit_runs():
    campaign = ART / "failure-campaign"
    data = ART / "failure-data"
    protocol = json.loads((campaign / "PROTOCOL.json").read_text())
    state = json.loads((campaign / "STATUS.json").read_text())
    expected = {(c, s) for c in protocol["cases"] for s in SYSTEMS}
    assert set(map(tuple, state["completed"])) == expected and len(expected) == 12
    assert not any(state[k] for k in ("failed", "active", "pending"))
    source = Path(protocol["source"])
    snap = source / "MECHANISM_SOURCE_SNAPSHOT.json"
    assert sha(snap) == protocol["source_snapshot_sha256"]
    files = json.loads(snap.read_text())["files"]
    for path, digest in files.items():
        assert sha(source / path) == digest, path
    oldsource = ROOT / "output/three-system-20260908/source-v6"
    oldfiles = json.loads((oldsource / "MECHANISM_SOURCE_SNAPSHOT.json").read_text())["files"]
    changed = sorted(k for k in files.keys() | oldfiles.keys() if files.get(k) != oldfiles.get(k))
    assert changed == ["benchmark/AegisKV/experiments/scripts/run_three_system_mechanisms.py"]
    result = {}
    baseline = load_case(data / "f0-natural")
    for case in protocol["cases"]:
        case_data = load_case(data / case)
        for s, d in case_data.items():
            m = d["manifest"]
            raw = campaign / "runs" / case / f"{s}.json.gz"
            assert d["extractor_sha256"] == sha(Path(__file__).with_name("three_system_data.py"))
            assert d["audit"]["status"] == m["status"] == "PASS"
            assert m["source_snapshot_sha256"] == sha(snap)
            assert m["cpu_calibration_sha256"] == protocol["cpu_calibration_sha256"]
            assert m["raw_sha256"] == sha(raw)
            assert m == json.loads(raw.with_name(f"{s}.manifest.json").read_text())
            if case != "f0-natural":
                assert (
                    m["failure_reference_sha256"] == baseline["mooncake"]["manifest"]["raw_sha256"]
                )
            assert len(d["workflows"]) == 160 and len(d["requests"]) == 1304
            result[f"{case}/{s}"] = {
                "raw_sha256": sha(raw),
                "data_sha256": sha(data / case / f"{s}.json"),
            }
    for s, d in baseline.items():
        prior = json.loads(
            (ROOT / f"output/three-system-20260908/data-final/f0-natural/{s}.json").read_text()
        )
        assert [(r["workflow_id"], r["wct_s"]) for r in d["workflows"]] == [
            (r["workflow_id"], r["wct_s"]) for r in prior["workflows"]
        ]

    # Reconstruct candidate crossings independently from the baseline scheduler
    # trace; verify all three chosen focuses against the frozen input rule.
    with gzip.open(campaign / "runs/f0-natural/mooncake.json.gz", "rt") as handle:
        raw = json.load(handle)
    tokens = {r["span_id"]: r["prompt_tokens"] for r in baseline["mooncake"]["requests"]}
    ends = {
        w: max(r["completed_ns"] for r in baseline["mooncake"]["requests"] if r["workflow_id"] == w)
        for w in baseline["mooncake"]["manifest"]["workload"]["workflow_ids"]
    }
    crossings = {}
    for step in raw["representative"]["continuous_batch_scheduler"]["steps"]:
        for part in step["participants"]:
            rid = part["request_id"]
            if tokens[rid] < 16384:
                continue
            threshold = tokens[rid] * 600 // 1000
            before = part["num_computed_tokens_before"]
            after = part["num_computed_tokens_after"]
            if before <= threshold < after:
                at = step["start_ns"] + (step["planned_end_ns"] - step["start_ns"]) * (
                    threshold - before
                ) // (after - before)
                crossings[rid] = min(at, crossings.get(rid, at))
    counts = {rid: sum(t < at for t in ends.values()) for rid, at in crossings.items()}
    plans = []
    for q in (25, 50, 75):
        plan = json.loads((campaign / f"runs/f1-q{q}/failure-plan.json").read_text())["events"][0]
        chosen = min(
            crossings, key=lambda rid: (abs(counts[rid] * 1000 - q * 10 * 160), crossings[rid], rid)
        )
        assert plan["focus_span_id"] == chosen
        assert plan["reference_at_ns"] == crossings[chosen]
        assert plan["workload_position"]["reference_completed_workflow_count"] == counts[chosen]
        plans.append({"nominal_percent": q, "completed": counts[chosen], "span_id": chosen})
    return {
        "runs": result,
        "source_files": len(files),
        "core_identical_to_v6": True,
        "baseline_wct_identical_to_v6": True,
        "selection_reconstructed": plans,
        "protocol_sha256": sha(campaign / "PROTOCOL.json"),
    }


def audit_values():
    data = load_case(ROOT / "output/three-system-20260908/data-final/f0-revisit")
    order = list(csv.DictReader((OUT / "workflow-order.csv").open()))
    ids = [r["workflow_id"] for r in order]
    base = data["mooncake"]["workflows"]
    expected = sorted(base, key=lambda r: (r["wct_s"], r["workflow_id"]))
    assert ids == [r["workflow_id"] for r in expected]
    service = controller_service(data)
    specs = {
        "wct": ("wct_s", False),
        "wct-difference": ("wct_s", True),
        "dram-hit": ("dram_hit_pct", False),
        "scheduler-queue": ("mean_scheduler_queue_s", False),
        "hbm-wait": ("mean_foreground_hbm_wait_s", False),
        "controller-service-difference": (None, True),
        "background-copy": ("background_copy_gib", False),
        "peer-copy": ("peer_copy_gib", False),
    }
    for suffix, (key, difference) in specs.items():
        rows = list(csv.DictReader((OUT / f"f0-revisit-{suffix}.csv").open()))
        assert [r["workflow_id"] for r in rows] == ids
        vals = {
            s: {
                r["workflow_id"]: (r[key] if key else service[s][i])
                for i, r in enumerate(data[s]["workflows"])
            }
            for s in SYSTEMS
        }
        for row in rows:
            for s in SYSTEMS:
                value = vals[s][row["workflow_id"]] - (
                    vals["mooncake"][row["workflow_id"]] if difference else 0
                )
                assert np.isclose(float(row[s]), value, rtol=0, atol=1e-9)
    for name, key in [("wct-cdf", "wct_s"), ("ttft-cdf", "ttft_ns")]:
        rows = list(csv.DictReader((OUT / f"f0-revisit-{name}.csv").open()))
        for s in SYSTEMS:
            source = data[s]["workflows"] if key == "wct_s" else data[s]["requests"]
            col = "wct_s" if key == "wct_s" else "ttft_s"
            scale = 1 if key == "wct_s" else 1e9
            assert np.allclose(
                sorted(float(r[col]) for r in rows if r["system"] == s),
                sorted(r[key] / scale for r in source),
            )
    for s in SYSTEMS:
        rows = [
            r for r in csv.DictReader((OUT / "f0-revisit-tpot-tail.csv").open()) if r["system"] == s
        ]
        vals = np.array(
            [
                r["request_tpot_ns"] / 1e6
                for r in data[s]["requests"]
                if r["request_tpot_ns"] is not None
            ]
        )
        assert sum(int(r["count"]) for r in rows) == len(vals) == 2432
        for row in rows:
            assert np.isclose(float(row["survival_ge"]), np.mean(vals >= float(row["tpot_ms"])))
    return {
        "paired_workflows": len(ids),
        "workflow_curves_checked": len(specs),
        "request_and_workflow_distributions_checked": True,
        "inclusive_tpot_survival_checked": True,
        "failure_values": audit_failure_values(ids),
    }


def audit_failure_values(ids):
    data = ART / "failure-data"
    baseline = load_case(data / "f0-natural")
    summaries = list(csv.DictReader((OUT / "failure-progress-p95-penalty.csv").open()))
    phases = list(csv.DictReader((OUT / "failure-focal-recovery-phases.csv").open()))
    assert len(summaries) == len(phases) == 9
    for q in (25, 50, 75):
        case = f"f1-q{q}"
        current = load_case(data / case)
        plotted = list(csv.DictReader((OUT / f"{case}-workflow-penalty.csv").open()))
        assert [r["workflow_id"] for r in plotted] == ids
        for s in SYSTEMS:
            prior = {r["workflow_id"]: r["wct_s"] for r in baseline[s]["workflows"]}
            observed = {r["workflow_id"]: r["wct_s"] for r in current[s]["workflows"]}
            differences = np.array([observed[w] - prior[w] for w in ids])
            assert np.allclose([float(r[s]) for r in plotted], differences, rtol=0, atol=1e-9)
            summary = [r for r in summaries if r["case"] == case and r["system"] == s]
            phase = [r for r in phases if r["case"] == case and r["system"] == s]
            assert len(summary) == len(phase) == 1
            summary, phase = summary[0], phase[0]
            assert np.isclose(float(summary["mean_wct_delta_s"]), differences.mean())
            assert np.isclose(float(summary["p95_wct_delta_s"]), np.percentile(differences, 95))
            event = current[s]["manifest"]["failure_schedule"]["events"][0]
            focus = event["focus_span_id"]
            assert phase["focus_span_id"] == focus
            progress = event["workload_position"]["reference_completed_workflow_count"] / 160 * 100
            assert (
                float(summary["reference_progress_pct"])
                == float(phase["reference_progress_pct"])
                == progress
            )
            failures = [r for r in current[s]["failures"] if r["span_id"] == focus]
            materialized = [
                r
                for r in current[s]["recovery_events"]
                if r["span_id"] == focus and r["event"] == "CONTINUOUS_RECOVERY_PREFIX_MATERIALIZED"
            ]
            assert len(failures) == len(materialized) == 1
            failed = failures[0]
            start = failed["failure_at_ns"]
            prefix = materialized[0]["timestamp_ns"]
            end = failed["resume_decode_start_ns"]
            assert start <= prefix <= end
            for key, expected in {
                "prefix_materialization_s": (prefix - start) / 1e9,
                "suffix_to_resume_s": (end - prefix) / 1e9,
                "resume_delay_s": (end - start) / 1e9,
            }.items():
                assert np.isclose(float(phase[key]), expected, rtol=0, atol=1e-9)
            for key in ("restored_peer_tokens", "restored_store_tokens", "recompute_tokens"):
                assert int(phase[key]) == failed[key]
    return {
        "paired_workflow_figures": 3,
        "tail_and_phase_rows": 9,
        "event_boundaries_checked": True,
    }


def audit_media(selection, prepare):
    RENDER.mkdir(parents=True, exist_ok=True)
    result = {}
    pieces = []
    font = ImageFont.truetype(findfont("DejaVu Sans"), 19)
    for row in selection["figures"]:
        name = row["name"]
        for ext, digest in row["files"].items():
            assert sha(OUT / f"{name}.{ext}") == digest, (name, ext)
        with Image.open(OUT / f"{name}.png") as im:
            im.verify()
        ET.parse(OUT / f"{name}.svg")
        if row["evidence"] == "design":
            ET.parse(OUT / f"{name}.drawio")
        with pymupdf.open(OUT / f"{name}.pdf") as pdf:
            assert len(pdf) == 1
            page = pdf[0]
            assert abs(page.rect.width / 72 - row["width_in"]) < 0.001
            spans = [
                s
                for b in page.get_text("dict")["blocks"]
                if "lines" in b
                for line in b["lines"]
                for s in line["spans"]
                if s["text"].strip()
            ]
            assert spans
            fonts = sorted({s["font"] for s in spans})
            assert all(f.startswith("DejaVuSans") and "Mono" not in f for f in fonts), (
                name,
                fonts,
            )
            main_spans = [s for s in spans if not s["flags"] & 1]
            minimum = min(s["size"] for s in main_spans)
            assert minimum >= 9.9, (name, minimum)
            for span in spans:
                b = pymupdf.Rect(span["bbox"])
                assert (
                    b.x0 >= -1
                    and b.y0 >= -1
                    and b.x1 <= page.rect.width + 1
                    and b.y1 <= page.rect.height + 1
                ), (name, span["text"], b)
            if prepare:
                page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).save(RENDER / f"{name}.png")
                page.get_pixmap(matrix=pymupdf.Matrix(2, 2), colorspace=pymupdf.csGRAY).save(
                    RENDER / f"{name}.gray.png"
                )
        result[name] = {
            "pdf_sha256": sha(OUT / f"{name}.pdf"),
            "png_sha256": sha(OUT / f"{name}.png"),
            "minimum_main_font_pt": minimum,
            "fonts": fonts,
            "width_in": row["width_in"],
        }
        if prepare:
            im = Image.open(RENDER / f"{name}.png").convert("RGB")
            piece = Image.new("RGB", (1040, im.height + 40), "white")
            ImageDraw.Draw(piece).text((10, 4), row["id"] + "  " + name, font=font, fill="black")
            piece.paste(im, (12, 38))
            pieces.append(piece)
    if prepare:
        for i in range(0, len(pieces), 3):
            group = pieces[i : i + 3]
            sheet = Image.new(
                "RGB", (1040, sum(p.height for p in group) + 15 * (len(group) - 1)), "#E9EBED"
            )
            y = 0
            for p in group:
                sheet.paste(p, (0, y))
                y += p.height + 15
            sheet.save(RENDER / f"final-contact-{i // 3 + 1:02d}.png")
        (ART / "PDF_METADATA.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def audit_presentation_revision(selection):
    archive = OUT / "before-best-paper-review"
    data_files = [f"{r['name']}.csv" for r in selection["figures"] if "csv" in r["files"]]
    assert len(data_files) == 28
    data_files.append("workflow-order.csv")
    for name in data_files:
        assert sha(OUT / name) == sha(archive / name), name
    reference_manifest = (
        ROOT / "benchmark/AegisKV/docs/related_works/figure-references-20260908/manifest.json"
    )
    references = json.loads(reference_manifest.read_text())
    assert len(references) == 4
    for row in references:
        assert sha(ROOT / row["path"]) == row["pdf_sha256"]
    layout = json.loads((ART / "MARKDOWN_LAYOUT.json").read_text())
    assert layout["status"] == "RENDERED" and layout["loaded"] and layout["images"] == 33
    assert layout["source_sha256"] == sha(DIRECTORY / "Paper_Draft.md")
    assert layout["html_sha256"] == sha(OUT / "paper-story.html")
    assert len(layout["pairedRows"]) == 6
    for pair in layout["pairedRows"]:
        assert len(pair) == 2 and abs(pair[0]["y"] - pair[1]["y"]) <= 2
    assert layout["overflow"]["document"] <= layout["overflow"]["viewport"]
    return {
        "unchanged_figure_csvs": 28,
        "unchanged_workflow_order": True,
        "reference_pdf_bindings": 4,
        "reference_manifest_sha256": sha(reference_manifest),
        "markdown_layout_sha256": sha(ART / "MARKDOWN_LAYOUT.json"),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prepare-visuals", action="store_true")
    args = p.parse_args()
    selection_file = DATA / "paper-story-selection.json"
    selection = json.loads(selection_file.read_text())
    for name, digest in selection["manifest_bindings"].items():
        path = ROOT / name
        assert sha(path) == digest
        for source, expected in json.loads(path.read_text())["input_bindings"].items():
            assert sha(ROOT / source) == expected, source
    assert len(selection["figures"]) == 33
    assert {old for r in selection["figures"] for old in r["old_ids"]} == {
        f"P{i:02d}" for i in range(1, 22)
    }
    groups = selection["layout_groups"]
    by_name = {r["name"]: r for r in selection["figures"]}
    assert [name for group in groups for name in group] == list(by_name)
    assert sum(len(g) == 2 for g in groups) == 6
    for group in groups:
        assert len(group) in (1, 2)
        if len(group) == 2:
            assert all(by_name[n]["width_in"] < 5 for n in group)
    media = audit_media(selection, args.prepare_visuals)
    if args.prepare_visuals:
        print(
            json.dumps(
                {"status": "METADATA_CHECKED_RENDERED_FOR_VISUAL_REVIEW", "figures": len(media)}
            )
        )
        return
    runs = audit_runs()
    values = audit_values()
    presentation = audit_presentation_revision(selection)
    review = json.loads((ART / "VISUAL_REVIEW.json").read_text())
    assert review["status"] == "REVIEWED" and set(review["figures"]) == set(media)
    for name, d in media.items():
        assert review["figures"][name]["pdf_sha256"] == d["pdf_sha256"]
        assert review["figures"][name]["render_sha256"] == sha(RENDER / f"{name}.png")
    placement = OUT / "paper-story-placement.pdf"
    assert sha(placement) == review["placement_pdf_sha256"]
    documents = [
        DIRECTORY / p
        for p in (
            "FIGURES.md",
            "Paper_Draft.md",
            "Old_Figures.md",
            "PAPER_FIGURE_REVIEW.md",
            "PAPER_FAILURE_PROTOCOL.md",
        )
    ]
    documents.extend(
        ROOT / "benchmark/AegisKV/docs/paper" / p
        for p in ("BEST_PAPER_FIGURE_REVIEW.md", "RELATED_FIGURE_REVIEW.md")
    )
    story = documents[1].read_text()
    assert re.findall(r"^## (.+)$", story, re.M) == ["Motivation", "System Design", "Evaluation"]
    assert set(re.findall(r'<img src="[^"\n]+/([^/]+)\.png"', story)) == set(media)
    links = 0
    for doc in documents:
        targets = re.findall(r"\]\(([^)]+)\)", doc.read_text())
        targets += re.findall(r'<img src="([^"]+)"', doc.read_text())
        for target in targets:
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path = (doc.parent / target.split("#", 1)[0]).resolve()
            assert path.exists() or path == ART / "DELIVERY_AUDIT.json", (doc, target)
            if "#paper-" in target:
                assert f'<a id="{target.split("#", 1)[1]}"' in path.read_text(), target
            links += 1
    old_section = (
        documents[2]
        .read_text()
        .split("<!-- THREE_SYSTEM_REVIEW_START -->")[1]
        .split("<!-- THREE_SYSTEM_REVIEW_END -->")[0]
    )
    assert len(set(re.findall(r"!\[[^\]]*\]\([^\n)]+/([^/]+)\.png\)", old_section))) == 186
    oldaudit = json.loads(
        (ROOT / "output/three-system-20260908/campaign-final/DELIVERY_AUDIT.json").read_text()
    )
    for name, record in oldaudit["figures_by_name"].items():
        for ext, digest in record["files"].items():
            assert sha(ROOT / f"output/pdf/three-system-20260908/{name}.{ext}") == digest
    result = {
        "status": "PASS",
        "figures": len(media),
        "design_figures": sum(r["evidence"] == "design" for r in selection["figures"]),
        "paired_rows": 6,
        "original_21_figures_accounted_for": True,
        "original_186_exports_unchanged": True,
        "local_links_checked": links,
        "runs": runs,
        "plotted_values": values,
        "presentation_revision": presentation,
        "figures_by_name": media,
        "selection_sha256": sha(selection_file),
        "documents": {str(d.relative_to(ROOT)): sha(d) for d in documents},
        "visual_review_sha256": sha(ART / "VISUAL_REVIEW.json"),
        "scope": "Provenance, paired modeled values, exports, and documents. Not native-system performance or full Algorithm 3 certification.",
    }
    (ART / "DELIVERY_AUDIT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "status",
                    "figures",
                    "design_figures",
                    "paired_rows",
                    "original_186_exports_unchanged",
                    "local_links_checked",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
