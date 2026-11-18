"""Concrete Agent sublease and independent AIMD illustrations; editable sources."""
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pymupdf
import build_paper_story_diagrams as native
from build_paper_story_diagrams import Diagram, INK, GRAY, BLUE, ORANGE, GREEN, RED, PALE, PB, PO, PG
from paper_paths import ROOT
from three_system_data import sha

OUT = ROOT / "output/pdf/aegiskv-agent-lease-20260908"
TMP = ROOT / "tmp/pdfs/agent-lease-native"


def overview():
    native.overview()
    p = OUT / "system-overview.drawio"
    tree = ET.parse(p)
    changes = {
        "dag-scope": "Agent / branch identity",
        "alg1": "1  Request Slack", "state1": "Agent state; fixed within request",
        "alg2": "2  Agent subleases", "state2": "credit shares; releasable tails Q",
        "alg3": "3  Guarded AIMD", "state3": "memory ceiling + step warning",
        "store-refs": "One physical copy; Agent A/B leases",
    }
    for c in tree.iter("mxCell"):
        if c.get("id") in changes:
            c.set("value", changes[c.get("id")])
    tree.write(p, encoding="utf-8", xml_declaration=True)


def dag_value():
    d = Diagram("design-joint-wct", 650)
    d.text("title", "Shared backup value follows the workflow join", 18, 5, 1164, bold=True)
    states = [("Without x", 7, 2, 12), ("Only A uses x", 3, 2, 12), ("A and B use x", 3, 0, 10)]
    for i, (label, ra, rb, wct) in enumerate(states):
        y = 78 + 160 * i
        d.text(f"state{i}", label, 18, y + 17, 245, 95, bold=True)
        for agent, duration, recovery, offset, color, fill in [("A", 3, ra, 0, ORANGE, PO), ("B", 8, rb, 57, BLUE, PB)]:
            start, unit = 278, 56
            d.box(f"{i}{agent}-base", f"{agent}: {duration}", start, y + offset, duration * unit, 42, fill=fill, stroke=color)
            if recovery:
                d.box(f"{i}{agent}-recovery", f"Recovery {recovery}" if recovery > 2 else str(recovery),
                    start + duration * unit, y + offset, recovery * unit, 42, dashed=True, stroke=color)
            end = start + (duration + recovery) * unit
            join = start + (wct - 2) * unit
            d.path(f"{i}{agent}-join", [(end, y + offset + 21), (join - 12, y + offset + 21),
                (join - 12, y + 50), (join, y + 50)], color=color)
        d.box(f"join{i}", "Join: 2", 278 + (wct - 2) * 56, y + 28, 112, 44, fill=PALE)
        d.text(f"wct{i}", f"WCT\n{wct} ms", 982, y + 17, 198, 77, bold=True, align="center")
        d.rule(f"row{i}", y + 134)
    d.text("share", "Agent order A → B:   W(A,x) = 12 − 12 = 0;   W(B,x) = 12 − 10 = 2 ms", 18, 576, 1164, 45)
    d.write()


def subleases():
    d = Diagram("design-agent-subleases", 620)
    d.text("title", "One physical chunk, separate remaining Agent credits", 18, 5, 1164, bold=True)
    for key, x, label, fill, stroke in [("root", 140, "R: internal", PALE, GRAY),
            ("tail", 475, "X: tail", PB, BLUE), ("other", 880, "Y: tail", PO, ORANGE)]:
        d.box(key, label, x, 65, 210, 57, fill=fill, stroke=stroke)
    d.path("prefix", [(350, 93), (475, 93)], color=GRAY)
    d.text("queue", "Q = {X, Y}; each chunk is 1 GiB; R keeps its credit while internal", 18, 145, 1164)
    for i, (title, a, b, y, root) in enumerate([
            ("Before rent", 6, 4, "2", "7"), ("After rent\nδ = 2 ms/GiB", 4.8, 3.2, "0 → evict", "7"),
            ("Only A starts a new round", 6, 3.2, "released", "7")]):
        left = 20 + 398 * i
        d.text(f"state{i}", title, left, 210, 375, 64, bold=True, align="center")
        d.text(f"x{i}", "X", left, 300, 38, bold=True)
        d.box(f"a{i}", f"A: {a:g}", left + 50, 296, a * 28, 48, fill=PO, stroke=ORANGE)
        d.box(f"b{i}", f"B: {b:g}", left + 50 + a * 28, 296, b * 28, 48, fill=PB, stroke=BLUE)
        d.text(f"total{i}", f"Credit(X) = {a+b:g} ms", left, 357, 375, align="center")
        d.text(f"y{i}", f"Y: {y}", left + 25, 411, 345)
        d.text(f"r{i}", f"R: {root} (uncharged)", left + 25, 457, 345, color=GRAY)
    d.rule("rule", 526)
    d.text("dedup", "Same-round hits keep 9.2 ms; A's renewal cannot restore B's spent 0.8 ms", 18, 543, 1164, 53)
    d.write()


def admission():
    d = Diagram("design-prefix-admission", 590)
    d.text("title", "A single-chunk decision preserves every retained prefix", 18, 5, 1164, bold=True)
    states = [("Committed forest", "committed", None),
              ("Released tail; x pending", "aborted", "pending"),
              ("Copy complete", None, "committed")]
    for i, (title, a2, new) in enumerate(states):
        x = 22 + 398 * i
        d.text(f"h{i}", title, x, 70, 368, 44, bold=True, align="center")
        d.box(f"r{i}", "R", x + 5, 231, 75, 50, fill=PALE)
        for branch, y, color, fill in [("A", 163, ORANGE, PO), ("B", 306, BLUE, PB)]:
            d.text(f"{i}{branch}-label", "Agent " + branch, x + 112, y - 49, 240, color=color)
            d.box(f"{i}{branch}1", branch + "1", x + 125, y, 88, 50, fill=fill, stroke=color)
            d.path(f"{i}{branch}-fork", [(x+80,256),(x+100,256),(x+100,y+25),(x+125,y+25)], color=color)
        if a2:
            d.chunks(f"{i}a2", ["A2"], x + 261, 163, cell=88, height=50,
                     color=ORANGE, fill=PO, states=[a2])
            d.path(f"{i}a-edge", [(x+213,188),(x+261,188)], color=ORANGE)
        if new:
            d.chunks(f"{i}new", ["x"], x + 261, 306, cell=88, height=50,
                     color=BLUE, fill=PB, states=[new])
            d.path(f"{i}x-edge", [(x+213,331),(x+261,331)], color=BLUE, dashed=new != "committed")
        d.text(f"shared{i}", "R: one physical shared object", x, 395, 368, 55, align="center")
    d.rule("rule", 469)
    d.text("gates", "Free space: G(x) ≥ 0; replacement: G(x) > D(victims)", 18, 489, 1164, 45)
    d.text("commit", "Pending x is unreadable; a failed copy does not restore an already released A2", 18, 535, 1164, 38)
    d.write()


def budget():
    d = Diagram("design-guarded-aimd", 680)
    d.text("title", "Memory ceiling and foreground feedback control different decisions", 18, 5, 1164, bold=True)
    d.text("account-title", "Same 40 GiB physical device", 18, 63, 1164, bold=True)
    parts = [("Fixed\n16", 16, GRAY, PALE), ("Foreground\n14", 14, INK, "#D8DDE2"),
             ("Reserve\n4", 4, GREEN, PG), ("Backup\n4", 4, BLUE, PB), ("Free\n2", 2, ORANGE, PO)]
    x = 25
    for i, (text, gib, color, fill) in enumerate(parts):
        d.box(f"mem{i}", text, x, 123, gib * 28.6, 100, fill=fill, stroke=color, size=26)
        x += gib * 28.6
    d.text("cap", "Available backup ceiling C = 6 GiB; granted Q = 4 GiB; physical copies = 4 GiB", 18, 242, 1164, 49)
    d.rule("rule1", 307)
    d.text("stable", "Stable foreground", 22, 331, 360, bold=True, align="center")
    d.text("warn", "Normalized step warning", 423, 331, 360, bold=True, align="center")
    d.text("shrink", "Foreground grows by 4 GiB", 822, 331, 360, bold=True, align="center")
    for i, (label, color) in enumerate([("Q: 4 → 5 GiB", GREEN), ("Q: 4 → 2 GiB", RED), ("C: 6 → 2 GiB", BLUE)]):
        d.text(f"action{i}", label, 22 + i * 398, 403, 365, 50, color=color, bold=True, align="center")
    d.text("cond0", "4 valid windows + demand\n+ previous release complete", 22, 469, 365, 79, align="center")
    d.text("cond1", "β = 0.5; stop new copies\nwhile charged bytes exceed Q", 420, 469, 365, 79, align="center")
    d.text("cond2", "Clip grant immediately\nwait for physical free ACK", 818, 469, 365, 79, align="center")
    d.rule("rule2", 581)
    d.text("footer", "Q is permission, not occupied memory; a free command does not make bytes available", 18, 603, 1164, 51)
    d.write()


def main():
    native.OUT = OUT
    OUT.mkdir(parents=True, exist_ok=True); TMP.mkdir(parents=True, exist_ok=True)
    builders = {"system-overview": overview, "design-joint-wct": dag_value,
        "design-agent-subleases": subleases, "design-prefix-admission": admission,
        "design-guarded-aimd": budget, "commit-tier-timeline": native.commit}
    records = []
    for name, fn in builders.items():
        fn()
        source = OUT / (name + ".drawio")
        tree = ET.parse(source)
        ids = [c.get("id") for c in tree.iter("mxCell")]
        assert len(ids) == len(set(ids))
        for ext in ("pdf", "svg", "png"):
            dest = TMP / (name + ".pdf") if ext == "pdf" else OUT / (name + "." + ext)
            command = [native.CLI, "-x", "-f", ext, "-e", "-b", "0", "-o", str(dest), str(source)]
            if ext == "pdf": command.insert(5, "--crop")
            if ext == "png": command[5:5] = ["-s", "1.5"]
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        with pymupdf.open(TMP / (name + ".pdf")) as src:
            target = pymupdf.open(); page = target.new_page(width=504, height=src[0].rect.height * 504 / src[0].rect.width)
            page.show_pdf_page(page.rect, src, 0)
            target.set_metadata({"title": name, "subject": "Agent sublease / Guarded AIMD design illustration; not measured data"})
            target.save(OUT / (name + ".pdf")); target.close()
        records.append({"name": name, "evidence": "design", "width_in": 7,
            "files": {ext: sha(OUT / (name + "." + ext)) for ext in ("pdf", "svg", "png", "drawio")}})
        print(name, flush=True)
    (OUT / "diagrams-manifest.json").write_text(json.dumps({"figures": records,
        "generator_sha256": sha(__file__),
        "input_bindings": {str(Path(p).relative_to(ROOT)): sha(p) for p in [__file__, native.__file__, ROOT / "output/agent-lease-20260908/ALGORITHM_AUTHORITY.json"]},
        "authority": json.loads((ROOT / "output/agent-lease-20260908/ALGORITHM_AUTHORITY.json").read_text())}, indent=2) + "\n")


if __name__ == "__main__":
    main()
