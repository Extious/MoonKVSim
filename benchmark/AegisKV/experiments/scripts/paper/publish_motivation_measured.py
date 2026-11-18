#!/usr/bin/env python3
"""Publish the measured Motivation revision without replacing other chapters."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / "benchmark/AegisKV"
OUT = BASE / "exports/motivation-measured-exposure-20260921"
PAPER = BASE / "paper"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    data = json.loads((BASE / "experiments/data/motivation-compact-cc/recovery-costs-measured.json").read_text())
    assert data["cost_evidence"] == "physical_worker_microbenchmark"
    for name, digest in data["source_sha256"].items():
        assert sha(ROOT / name) == digest, name
    manifest = json.loads((OUT / "figures/trace-figures.json").read_text())
    for name, digest in manifest["source_sha256"].items():
        assert sha(ROOT / name) == digest, name
    for ext, digest in manifest["figures"]["recovery-exposure"]["files"].items():
        assert sha(OUT / f"figures/recovery-exposure.{ext}") == digest
    bindings = {"RESUME_JOB": "1517917"}
    assert data["job_ids"] == ["1517915", bindings["RESUME_JOB"]]
    for case in data["workflow_costs"]:
        bindings[f"{case['branch']}_COST"] = f"{case['recompute_s']:.1f}"
        bindings[f"{case['branch']}_LOSS"] = f"{case['wct_increase_s']:.1f}"

    def fill(name):
        value = (OUT / "sources" / name).read_text()
        for key, replacement in bindings.items():
            value = value.replace(f"@@{key}@@", replacement)
        assert not re.search(r"@@[A-Z0-9_]+@@", value), name
        return value

    main_path, md_path = PAPER / "main.tex", PAPER / "paper_draft.md"
    main_before, md_before = main_path.read_text(), md_path.read_text()
    appendix = fill("measurement_appendix.tex")
    begin = "% BEGIN MOTIVATION MEASUREMENT APPENDIX"
    end = "% END MOTIVATION MEASUREMENT APPENDIX"
    if begin in main_before:
        main_after = main_before[:main_before.index(begin)] + appendix.rstrip() + main_before[main_before.index(end)+len(end):]
    else:
        assert "\\appendix" not in main_before and main_before.count("\\end{document}") == 1
        main_after = main_before.replace("\\end{document}", "\n" + appendix + "\\end{document}")
    start = md_before.index("## 2. Background and Motivation")
    stop = md_before.index("## 3. AegisKV Design", start)
    md_after = md_before[:start] + fill("background_and_motivation.template.md") + md_before[stop:]
    md_marker = "## 附录 A. Motivation 测量协议"
    if md_marker in md_after:
        md_after = md_after[:md_after.index(md_marker)].rstrip() + "\n\n"
    md_after = md_after.rstrip() + "\n\n" + fill("measurement_appendix.template.md")
    # Store the exact concurrent versions incorporated into this publication.
    current = OUT / "before-integration"
    current.mkdir(exist_ok=True)
    for path in (main_path, md_path):
        target = current / path.name
        if not target.exists():
            target.write_bytes(path.read_bytes())
    assert main_path.read_text() == main_before and md_path.read_text() == md_before
    main_path.write_text(main_after)
    md_path.write_text(md_after)
    (PAPER / "background_and_motivation.tex").write_text(fill("background_and_motivation.template.tex"))
    shutil.copy2(OUT / "figures/recovery-exposure.pdf", PAPER / "figures/recovery-exposure.pdf")
    shutil.copy2(OUT / "figures/recovery-exposure.png", PAPER / "figures/preview/recovery-exposure.png")
    preserved = json.loads((OUT / "sources/preserved-figure1-sha256.json").read_text())
    assert all(sha(ROOT / path) == digest for path, digest in preserved.items())
    assert len(list(PAPER.glob("*.tex"))) == 4
    report = dict(bindings=bindings, figure1_unchanged=True,
                  main_other_chapters_preserved=main_before.replace("\\end{document}", "") in main_after.replace(appendix, "")
                  if begin not in main_before else None,
                  source_sha256={str(p.relative_to(ROOT)): sha(p) for p in (
                      main_path, md_path, PAPER / "background_and_motivation.tex",
                      PAPER / "figures/recovery-exposure.pdf", PAPER / "figures/preview/recovery-exposure.png")})
    (OUT / "publication.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
