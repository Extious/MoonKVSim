"""Small refusal-path tests in temporary fixtures; never run the live readiness gate."""

import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

SOURCE = Path(__file__).with_name("check.py")
spec = importlib.util.spec_from_file_location("readiness_gate", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
checks = []


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def refused(name, gate, operation):
    gate.group(name, operation)
    assert gate.checks[-1]["status"] == "NOT_READY", gate.checks[-1]
    checks.append(name)


with tempfile.TemporaryDirectory(prefix="aegiskv-readiness-selftest-") as directory:
    temporary = Path(directory)
    module.BASE = temporary
    module.ROOT = temporary
    module.PAPER = temporary / "paper"
    write(temporary / "walltime-primary-v3/STATUS.json", {"complete": False, "completed_runs": 179})
    gate = module.Gate({})
    refused("179conditions_cannot_pass", gate, gate.primary)
    write(temporary / "walltime-primary-v3/STATUS.json", {"complete": True, "completed_runs": 180})
    gate = module.Gate({})
    refused("complete_status_without_artifacts_cannot_pass", gate, gate.primary)
    text = temporary / "sealed.txt"
    text.write_text("first")
    gate = module.Gate({})
    digest = gate.sha(text)
    text.write_text("second")
    refused("mutation_during_read_cannot_pass", gate, lambda: gate.match(text, digest))
    refused(
        "empty_seal_cannot_pass", module.Gate({}), lambda: module.Gate({}).closure(temporary, {})
    )
    module.PAPER.mkdir()
    (module.PAPER / "main.pdf").write_bytes(b"new-pdf")
    (module.PAPER / "evaluation.tex").write_text("new evaluation")
    stale = {"status": "PASS", "manuscript_sha256": "0" * 64, "tex_sha256": "1" * 64}
    write(temporary / "EXPORT.json", stale)
    write(temporary / "VISUAL.json", stale)
    gate = module.Gate({"paper_export_review": "EXPORT.json", "paper_visual_review": "VISUAL.json"})
    refused("PASS_label_with_stale_pdf_hash_cannot_pass", gate, gate.paper_reviews)
    active = [
        "figures/primary.pdf",
        "figures/struct.pdf",
        "figures/resource.pdf",
        "figures/native.pdf",
    ]
    tex = "\n".join(r"\includegraphics[width=\textwidth]{" + ref + "}" for ref in active)
    tex += "\n% " + r"\includegraphics{figures/old-native.pdf}" + "\n"
    assert module.active_graphics(tex) == active
    checks.append("commented_or_unreferenced_old_figure_not_counted")
    required = {x: "irrelevant" for x in active}
    gate = module.Gate({"evaluation_figures": required})
    (module.PAPER / "evaluation.tex").write_text(tex + r"\includegraphics{figures/fifth.pdf}")
    refused("fifth_actual_Evaluation_figure_cannot_pass", gate, gate.figures)
    # Correct byte bindings cannot compensate for incomplete page coverage or a
    # TODO hidden in TeX comments. Fixtures contain no real manuscript/artifacts.
    (module.PAPER / "evaluation.tex").write_text("% TODO replace old v2 numbers\nEvaluation")

    def digest_file(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    render_hashes = {}
    for page in (1, 2):
        for mode in ("color", "gray"):
            path = temporary / f"page-{page}-{mode}.png"
            path.write_bytes(b"fixture-render")
            render_hashes[path.name] = digest_file(path)
    export = dict(
        manuscript_sha256=digest_file(module.PAPER / "main.pdf"),
        tex_sha256=digest_file(module.PAPER / "evaluation.tex"),
        evaluation_page_range=[1, 2],
        evaluation_figures=[],
        page_count=2,
    )
    write(temporary / "EXPORT.json", export)
    visual = dict(
        status="PASS",
        manuscript_sha256=export["manuscript_sha256"],
        tex_sha256=export["tex_sha256"],
        export_review_sha256=digest_file(temporary / "EXPORT.json"),
        scientific_or_publication_approval=False,
        render_sha256=render_hashes,
        color_pages_checked=[1],
        grayscale_pages_checked=[1],
        figures=[],
    )
    write(temporary / "VISUAL.json", visual)
    config = dict(
        paper_export_review="EXPORT.json", paper_visual_review="VISUAL.json", evaluation_figures={}
    )
    gate = module.Gate(config)
    refused("missing_final_Evaluation_page_review_cannot_pass", gate, gate.paper_reviews)
    visual["color_pages_checked"] = visual["grayscale_pages_checked"] = [1, 2]
    write(temporary / "VISUAL.json", visual)
    gate = module.Gate(config)
    refused("commented_TODO_cannot_pass", gate, gate.paper_reviews)
    export["evaluation_page_range"] = [2, 1]
    write(temporary / "EXPORT.json", export)
    visual["export_review_sha256"] = digest_file(temporary / "EXPORT.json")
    visual["color_pages_checked"] = visual["grayscale_pages_checked"] = []
    write(temporary / "VISUAL.json", visual)
    gate = module.Gate(config)
    refused("reversed_page_range_cannot_vacuously_pass", gate, gate.paper_reviews)
    assert "invalid or empty final Evaluation page range" in gate.checks[-1]["reason"]
    read_gate = module.Gate({})
    read_gate.read(temporary / "EXPORT.json")
    write(temporary / "EXPORT.json", {"replacement": True})
    refused("end_of_gate_input_mutation_cannot_pass", read_gate, read_gate.stable_inputs)

record = dict(
    status="PASS",
    tests=checks,
    count=len(checks),
    real_gate_executed=False,
    fixtures="temporary only",
    DES_runs=0,
    source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    selftest_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
)
Path(__file__).with_name("SELFTEST.json").write_text(
    json.dumps(record, indent=2, sort_keys=True) + "\n"
)
print(f"{len(checks)} temporary-fixture refusal/parser checks PASS; live gate not executed")
