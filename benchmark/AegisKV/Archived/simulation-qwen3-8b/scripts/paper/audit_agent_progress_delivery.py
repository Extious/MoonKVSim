"""Audit the current manuscript's two progress-triggered failure figures."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote
import pymupdf


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read(p):
    return json.loads(Path(p).read_text())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[5])
    args = p.parse_args()
    root = args.repo.resolve()
    docs = root/"benchmark/AegisKV/experiments"
    edition = read(docs/"ACTIVE_PAPER_EDITION.json")
    selection = read(root/edition["selection"])
    art = root/"output/agent80-20260909"
    out = root/edition["figures"]
    figures = selection["figures"]
    assert len(figures) == 14 and [r["id"] for r in figures] == [str(i) for i in range(1,15)]
    assert [r["name"] for r in figures][7:9] == ["eval-agent80-workflow-wct", "eval-agent80-position-wct"]
    assert [n for group in selection["layout_groups"] for n in group] == [r["name"] for r in figures]
    prior = read(art/"before-publication/paper-selection.json")
    original = {r["name"]: r["files"] for r in prior["figures"] if r["name"] != "eval-fixed-event-wct"}
    current = {r["name"]: r["files"] for r in figures}
    assert all(current[name] == files for name, files in original.items())
    for r in figures:
        directory = root/r.get("directory", edition["figures"])
        for ext, digest in r["files"].items():
            assert sha(directory/f'{r["name"]}.{ext}') == digest
    manifest_path = out/"agent80-figure-manifest.json"
    manifest = read(manifest_path)
    for path, digest in manifest["inputs"].items():
        assert sha(art/"campaign"/path) == digest
    audit = read(art/"campaign/RUN_AUDIT.json")
    assert audit["status"] == "PASS" and audit["full_runs"] == 24
    assert audit["F0_runs"] == 3 and audit["F1_runs"] == 21
    assert audit["protocol_sha256"] == sha(art/"campaign/PROTOCOL.json")
    assert len(audit["raw_runs_reconstructed"]) == 24
    for row in audit["raw_runs_reconstructed"]:
        run_manifest = read(art/"campaign/runs"/row["case"]/f'{row["system"]}.manifest.json')
        assert run_manifest["raw_sha256"] == row["raw_sha256"]
        assert run_manifest["summary_sha256"] == row["summary_sha256"]
    visual_path = out/"agent80-visual-review.json"
    visual = read(visual_path)
    assert visual["status"] == "PASS"
    for name, digests in visual["figures"].items():
        for ext, digest in digests.items():
            assert sha(out/f"{name}.{ext}") == digest
    text = (docs/"Paper_Draft.md").read_text()
    assert "<!-- AGENT80_SECTION_START -->" in text and "固定追加故障：同一 Workflow" not in text
    assert re.findall(r"\*\*图 (\d+)：", text) == [str(i) for i in range(1,15)]
    images = re.findall(r'<img src="([^"]+)"', text)
    assert len(images) == 14
    for path in images:
        assert (docs/unquote(path)).resolve().is_file()
    assert "{{" not in text
    template = docs/"scripts/paper/templates/revision-draft.md"
    assert selection["template_sha256"] == sha(template)
    normal = selection.get("normal_f0_override")
    if normal:
        assert sha(root/normal["manifest"]) == normal["sha256"]
        assert sha(root/normal["template"]) == normal["template_sha256"]
    assert "{{fig:eval-fixed-event-wct}}" not in template.read_text()
    metadata = []
    for name in ["eval-agent80-workflow-wct", "eval-agent80-position-wct"]:
        with pymupdf.open(out/f"{name}.pdf") as doc:
            assert len(doc) == 1 and abs(doc[0].rect.width-504) < .01
            spans = [s for b in doc[0].get_text("dict")["blocks"] if "lines" in b
                     for line in b["lines"] for s in line["spans"] if s["text"].strip()]
            assert min(s["size"] for s in spans) >= 9.9
            assert all(s["bbox"][0] >= -.1 and s["bbox"][1] >= -.1 and s["bbox"][2] <= doc[0].rect.width+.1 and
                       s["bbox"][3] <= doc[0].rect.height+.1 for s in spans)
            metadata.append({"name": name, "width_pt": doc[0].rect.width, "min_font_pt": min(s["size"] for s in spans)})
    result = {"status": "PASS", "paper_figures": 14, "new_figures": [8,9], "unchanged_export_sets": len(original),
              "new_complete_simulations": 24, "F0": 3, "F1": 21, "smoke_runs_excluded": 6,
              "repeats_per_condition": 1, "workflow_pairs": 3360, "focus_pairs": 21,
              "metadata": metadata, "paper_sha256": sha(docs/"Paper_Draft.md"),
              "selection_sha256": sha(root/edition["selection"]), "run_audit_sha256": sha(art/"campaign/RUN_AUDIT.json"),
              "visual_review_sha256": sha(visual_path),
              "scope": "24 raw-run reconstructions, two new figures visually reviewed at 177.8 mm, remaining 12 export sets hash-preserved, manuscript figure numbering and image links; no native performance certification"}
    (art/"DELIVERY_AUDIT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
