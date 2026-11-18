"""Bind final plots, reduced inputs, raw runs and the one frozen source."""

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import pymupdf
from paper_paths import DATA
from PIL import Image
from three_system_data import SYSTEMS, load_case, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--figures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[5]
    protocol = json.loads((args.campaign / "PROTOCOL.json").read_text())
    status = json.loads((args.campaign / "STATUS.json").read_text())
    assert not status["failed"] and not status["pending"] and not status["active"]
    expected = {(c, s) for c, cfg in protocol["cases"].items() for s in cfg.get("systems", SYSTEMS)}
    assert set(map(tuple, status["completed"])) == expected
    source = Path(protocol["source"])
    snapshot = source / "MECHANISM_SOURCE_SNAPSHOT.json"
    assert sha(snapshot) == protocol["source_snapshot_sha256"]
    for name, digest in json.loads(snapshot.read_text())["files"].items():
        assert sha(source / name) == digest, name
    calibration = Path(protocol["cpu_calibration"])
    assert sha(calibration) == protocol["cpu_calibration_sha256"]
    quotes = json.loads(calibration.read_text())
    runs = {}
    extractor = sha(Path(__file__).with_name("three_system_data.py"))
    for case, system in sorted(expected):
        path = args.data / case / f"{system}.json"
        data = json.loads(path.read_text())
        m = data["manifest"]
        assert data["extractor_sha256"] == extractor
        assert data["audit"]["status"] == m["status"] == "PASS"
        assert m["source_snapshot_sha256"] == sha(snapshot), (case, system, "mixed source")
        assert m["system"] == system and m["workload"]["workflows"] == 160
        scale = protocol["cases"][case].get("cpu-scale", 1)
        assert m["configuration"]["cpu_service_ns"] == round(quotes["admission_ns"][system] * scale)
        assert m["configuration"]["foreground_cpu_service_ns"] == round(
            quotes["foreground_lookup_ns"] * scale
        )
        raw = args.campaign / "runs" / case / f"{system}.json.gz"
        assert sha(raw) == m["raw_sha256"]
        assert m == json.loads(raw.with_name(f"{system}.manifest.json").read_text())
        if m["failure_reference_sha256"] is not None:
            assert m["failure_reference_sha256"] == sha(
                args.campaign / "runs/f0-natural/mooncake.json.gz"
            )
        runs[f"{case}/{system}"] = {
            "raw_sha256": m["raw_sha256"],
            "data_sha256": sha(path),
            "workflow_csv_sha256": sha(path.with_name(f"{system}-workflows.csv")),
            "request_csv_sha256": sha(path.with_name(f"{system}-requests.csv")),
        }
    for case, cfg in protocol["cases"].items():
        if "systems" not in cfg:
            data = load_case(args.data / case)
            configurations = [dict(d["manifest"]["configuration"]) for d in data.values()]
            for cfg in configurations:
                cfg.pop("cpu_service_ns")
            assert all(cfg == configurations[0] for cfg in configurations)
    records, figures = [], {}
    for file in args.figures.glob("*-figure-manifest.json"):
        records.extend(json.loads(file.read_text()))
    for record in records:
        name = record["name"]
        assert name not in figures, name
        media = {}
        for ext in ("png", "pdf", "svg"):
            path = args.figures / f"{name}.{ext}"
            media[ext] = sha(path)
            if f"{ext}_sha256" in record:
                assert media[ext] == record[f"{ext}_sha256"], path
        with Image.open(args.figures / f"{name}.png") as im:
            im.verify()
        ET.parse(args.figures / f"{name}.svg")
        with pymupdf.open(args.figures / f"{name}.pdf") as doc:
            assert len(doc) == 1
            page = doc[0]
            spans = [
                s
                for b in page.get_text("dict")["blocks"]
                if "lines" in b
                for line in b["lines"]
                for s in line["spans"]
                if s["text"].strip()
            ]
            assert spans, (name, "no searchable labels")
            native = record.get("type") == "editable_native_drawio"
            width = 7.2 if native else page.rect.width / 72
            # Log-axis powers use mathematical superscripts at a smaller size.
            main_spans = [s for s in spans if not s["flags"] & 1]
            minimum_font = min(s["size"] for s in main_spans) * width * 72 / page.rect.width
            assert minimum_font >= 9.9, (name, minimum_font)
            if not native:
                for span in spans:
                    box = pymupdf.Rect(span["bbox"])
                    assert box.x0 >= -1 and box.y0 >= -1
                    assert box.x1 <= page.rect.width + 1 and box.y1 <= page.rect.height + 1
        if native:
            path = args.figures / f"{name}.drawio"
            ET.parse(path)
            assert sha(path) == record["source_sha256"]
            media["drawio"] = sha(path)
        table = args.figures / f"{name}.csv"
        if table.exists():
            assert sha(table) == record["csv_sha256"]
            media["csv"] = sha(table)
        figures[name] = {
            "case": record.get("case"),
            "files": media,
            "recommended_width_in": width,
            "minimum_font_pt_at_that_width": minimum_font,
        }
    review_file = args.campaign / "VISUAL_REVIEW.json"
    review = json.loads(review_file.read_text())
    assert review["status"] == "PASS"
    assert set(review["reviewed_png_sha256"]) == set(figures)
    for name, info in figures.items():
        assert review["reviewed_png_sha256"][name] == info["files"]["png"], name
    assert len(figures) == 186, "final delivery figure coverage changed"
    inputs = json.loads((DATA / "publication-figure-inputs.json").read_text())
    workload = root / "benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-8b-160.jsonl"
    assert sha(workload) == inputs["input_bindings"][str(workload.relative_to(root))]
    prompts, contexts, counts = [], [], Counter()
    for line in workload.open():
        row = json.loads(line)
        prompts.append(row["prompt_tokens"])
        contexts.append(row["total_model_tokens"])
        counts[row["workflow_id"]] += 1
    assert sorted(prompts) == sorted(inputs["prompt_tokens"])
    assert sorted(contexts) == sorted(inputs["context_tokens"])
    assert sorted(counts.values()) == sorted(inputs["workflow_call_counts"])
    import_file = DATA / "motivation-real-cc/IMPORT.json"
    for row in json.loads(import_file.read_text())["files"]:
        assert sha(import_file.parent / row["copy"]) == row["sha256"]
    supporting = [
        DATA / p
        for p in (
            "publication-figure-inputs.json",
            "physical-pilot/pilot-cost-profile.json",
            "motivation-real-cc/IMPORT.json",
            "motivation-real-cc/RAW_RECONSTRUCTION.json",
            "motivation-real-cc/real-cc-workflow-parallel-gap.csv",
            "motivation-real-cc/real-cc-example-failure-position.csv",
        )
    ]
    original = json.loads((DATA / "figure-manifest.json").read_text())["input_bindings"]
    for path in supporting:
        assert sha(path) == original[str(path.relative_to(root))]
    index = root / "benchmark/AegisKV/experiments/FIGURES.md"
    documents = [index]
    paper = index.with_name("Paper_Draft.md")
    archive = index.with_name("Old_Figures.md")
    selection_file = DATA / "three-system-paper-selection.json"
    selection_info = None
    if paper.exists() or archive.exists():
        assert paper.exists() and archive.exists()
        documents += [paper, archive]
        selection = json.loads(selection_file.read_text())
        selected = {r["name"] for r in selection["figures"]}
        assert selected <= figures.keys()
        paper_text = paper.read_text()
        archive_text = archive.read_text().split("<!-- THREE_SYSTEM_REVIEW_START -->")[1].split(
            "<!-- THREE_SYSTEM_REVIEW_END -->"
        )[0]
        paper_names = set(re.findall(r"!\[[^\]]*\]\([^\n)]+/([^/]+)\.png\)", paper_text))
        paper_names.update(re.findall(r'<img src="[^"\n]+/([^/]+)\.png"', paper_text))
        archive_names = set(re.findall(r"!\[[^\]]*\]\([^\n)]+/([^/]+)\.png\)", archive_text))
        story_file = DATA / "paper-story-selection.json"
        if story_file.exists():
            story = json.loads(story_file.read_text())
            story_names = {r["name"] for r in story["figures"]}
            assert paper_names == story_names
            assert archive_names == figures.keys(), "the narrative edition archives all original exports"
            selection_info = {
                "schema": "separate_narrative_edition",
                "selection_sha256": sha(story_file),
                "paper_figures": len(story_names),
                "archived_current_figures": len(archive_names),
                "scope": "This audit covers the original source-v6 data and 186 exports. New narrative exports and fault runs are separately audited.",
                "story_audit": "output/paper-story-20260908/DELIVERY_AUDIT.json",
            }
        else:
            assert paper_names == selected
            assert archive_names == figures.keys() - selected
            selection_info = {
                "selection_sha256": sha(selection_file),
                "paper_figures": len(selected),
                "archived_current_figures": len(archive_names),
                "selected_names": sorted(selected),
                "previous_index_sha256": sha(args.campaign / "FIGURES-before-split.txt"),
                "scope": selection["selection_basis"],
            }
    local_links = 0
    for document in documents:
        text = document.read_text()
        anchors = re.findall(r'<a id="([^"]+)"', text)
        assert len(anchors) == len(set(anchors)), (document, "duplicate anchors")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if target.startswith("#"):
                # Other historical heading anchors are generated by Markdown.
                if target.startswith(("#three-system", "#paper-")):
                    assert target[1:] in anchors
                continue
            path = (document.parent / target.split("#", 1)[0]).resolve()
            assert path.exists(), (document, target)
            local_links += 1
    result = {
        "status": "PASS",
        "runs": len(runs),
        "cases": len(protocol["cases"]),
        "figures": len(figures),
        "local_markdown_links": local_links,
        "source_snapshot_sha256": sha(snapshot),
        "source_files": len(json.loads(snapshot.read_text())["files"]),
        "protocol_sha256": sha(args.campaign / "PROTOCOL.json"),
        "cpu_quotes_sha256": sha(calibration),
        "index_sha256": sha(index),
        "index_documents": {str(p.relative_to(root)): sha(p) for p in documents},
        "paper_selection": selection_info,
        "runs_by_id": runs,
        "figures_by_name": figures,
        "generator_files": {
            str(p.relative_to(root)): sha(p)
            for p in [
                *Path(__file__).parent.glob("*three_system*.py"),
                *(
                    Path(__file__).with_name(name)
                    for name in (
                        "figure_style.py",
                        "build_reviewed_diagrams.py",
                        "build_submission_diagrams.py",
                    )
                ),
            ]
        },
        "supporting_inputs": {str(p.relative_to(root)): sha(p) for p in supporting},
        "visual_review": "PNG/PDF contact sheets and individual figure inspection; VISUAL_REVIEW.json",
        "visual_review_sha256": sha(review_file),
        "evidence": "modeled_exploration; no native serving or QoS certification",
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if not isinstance(v, dict)}))


if __name__ == "__main__":
    main()
