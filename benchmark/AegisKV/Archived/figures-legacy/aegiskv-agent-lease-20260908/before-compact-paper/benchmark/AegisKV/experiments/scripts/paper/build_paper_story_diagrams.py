"""Concrete mechanism illustrations, with native editable Draw.io exports."""

import argparse
import json
import subprocess
from pathlib import Path
import xml.etree.ElementTree as ET

import pymupdf
from paper_paths import ROOT
from three_system_data import sha

OUT = ROOT / "output/pdf/aegiskv-paper-story-20260908"
TMP = ROOT / "tmp/pdfs/paper-story-native"
CLI = "/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli"
INK, GRAY, BLUE, ORANGE, GREEN, RED = (
    "#303943",
    "#69737E",
    "#0072B2",
    "#B86B00",
    "#007D60",
    "#B83C46",
)
PALE, PB, PO, PG, PR = "#EEF0F3", "#E4F1F8", "#FFF0DB", "#E9F5EF", "#FBECEE"
EXAMPLES = {
    "slack": {"durations_s": {"A": 3, "B": 8}, "margin_s": 1, "epoch": 7},
    "prefix": {
        "chunk_bytes": "b",
        "logical_references": 6,
        "physical_chunks": 4,
        "closure": ["C1", "C2-A", "C2-B"],
        "freed_chunks": 3,
    },
    "budget": {
        "capacity_gib": 40,
        "fixed_gib": 16,
        "primary_before_gib": 12,
        "primary_after_gib": 16,
        "reserve_gib": 6,
        "charged_before_gib": 6,
        "charged_after_ack_gib": 2,
    },
    "commit": {
        "peer_prefix_chunks": 2,
        "dram_prefix_chunks": 1,
        "logical_order": ["seal", "peer_ack", "failure", "materialize", "resume"],
    },
}


class Diagram:
    def __init__(self, name, height):
        self.name, self.height = name, height
        self.doc = ET.Element("mxfile", host="app.diagrams.net", version="31.1.5")
        page = ET.SubElement(self.doc, "diagram", id=name, name=name)
        graph = ET.SubElement(
            page,
            "mxGraphModel",
            grid="1",
            gridSize="10",
            page="1",
            pageWidth="1200",
            pageHeight=str(height),
            background="#FFFFFF",
            math="0",
        )
        self.root = ET.SubElement(graph, "root")
        ET.SubElement(self.root, "mxCell", id="0")
        ET.SubElement(self.root, "mxCell", id="1", parent="0")
        self.box("canvas", "", 0, 0, 1200, height, stroke="#FFFFFF")

    def box(
        self,
        key,
        text,
        x,
        y,
        w,
        h,
        *,
        fill="#FFFFFF",
        stroke=INK,
        dashed=False,
        size=26,
        bold=False,
        label=False,
        align="center",
        shape=None,
    ):
        style = (
            f"rounded=0;whiteSpace=wrap;html=0;strokeWidth=1.6;strokeColor={stroke};"
            f"fillColor={fill};fontFamily=DejaVu Sans;fontSize={size};fontColor={stroke};"
            f"align={align};verticalAlign=middle;spacing=3;"
        )
        if label:
            style += "strokeColor=none;fillColor=none;"
        if dashed:
            style += "dashed=1;dashPattern=4 3;"
        if bold:
            style += "fontStyle=1;"
        if shape:
            style += f"shape={shape};"
        c = ET.SubElement(
            self.root, "mxCell", id=key, value=text, style=style, vertex="1", parent="1"
        )
        ET.SubElement(
            c,
            "mxGeometry",
            x=str(x),
            y=str(y),
            width=str(w),
            height=str(h),
            attrib={"as": "geometry"},
        )

    def text(self, key, text, x, y, w, h=38, *, color=INK, bold=False, align="left", size=26):
        self.box(key, text, x, y, w, h, label=True, stroke=color, bold=bold, align=align, size=size)

    def path(self, key, points, *, color=INK, dashed=False, arrow=True, width=2.3):
        style = f"edgeStyle=none;rounded=0;strokeColor={color};strokeWidth={width};endArrow={'block' if arrow else 'none'};endSize=7;endFill=1;"
        if dashed:
            style += "dashed=1;dashPattern=5 4;"
        c = ET.SubElement(self.root, "mxCell", id=key, edge="1", parent="1", style=style)
        g = ET.SubElement(c, "mxGeometry", relative="1", attrib={"as": "geometry"})
        ET.SubElement(
            g, "mxPoint", x=str(points[0][0]), y=str(points[0][1]), attrib={"as": "sourcePoint"}
        )
        ET.SubElement(
            g, "mxPoint", x=str(points[-1][0]), y=str(points[-1][1]), attrib={"as": "targetPoint"}
        )
        if len(points) > 2:
            arr = ET.SubElement(g, "Array", attrib={"as": "points"})
            for x, y in points[1:-1]:
                ET.SubElement(arr, "mxPoint", x=str(x), y=str(y))

    def chunks(self, key, labels, x, y, *, cell=72, height=42, color=INK, fill=PALE, states=None):
        for i, label in enumerate(labels):
            state = states[i] if states else "committed"
            self.box(
                f"{key}-{i}",
                label,
                x + i * (cell + 5),
                y,
                cell,
                height,
                fill=fill if state == "committed" else "#FFFFFF",
                stroke=RED if state == "aborted" else color,
                dashed=state != "committed",
            )
            if state == "aborted":
                self.path(
                    f"{key}-{i}-x",
                    [
                        (x + i * (cell + 5) + 5, y + height - 5),
                        (x + i * (cell + 5) + cell - 5, y + 5),
                    ],
                    color=RED,
                    arrow=False,
                )

    def rule(self, key, y):
        self.path(key, [(18, y), (1182, y)], color="#CAD0D6", arrow=False, width=1.2)

    def write(self):
        ET.indent(self.doc)
        ET.ElementTree(self.doc).write(
            OUT / (self.name + ".drawio"), encoding="utf-8", xml_declaration=True
        )


def overview():
    d = Diagram("system-overview", 680)
    d.text("application", "Workflow dependencies", 18, 6, 380, bold=True)
    for key, txt, x, y in [("a", "A", 80, 70), ("b", "B", 80, 145), ("j", "Join", 260, 106)]:
        d.box(
            "dag-" + key,
            txt,
            x,
            y,
            75,
            50,
            fill=PG if key != "j" else "#FFFFFF",
            stroke=GREEN,
            shape="ellipse",
        )
    d.path("a-j", [(155, 95), (225, 95), (225, 131), (260, 131)], color=GREEN)
    d.path("b-j", [(155, 170), (225, 170), (225, 131), (260, 131)], color=GREEN)
    d.text("dag-scope", "Consumer + DAG version", 20, 198, 380, color=GREEN)
    d.path("tickets", [(335, 131), (415, 131)], color=GREEN, dashed=True)
    d.text("control-title", "AegisKV control state", 445, 6, 750, bold=True)
    d.text("alg1", "1  Slack tickets", 445, 58, 275, bold=True)
    d.text("state1", "consumer, time margin, expiry", 742, 58, 435)
    d.text("alg2", "2  Prefix admission", 445, 104, 292, bold=True)
    d.text("state2", "shared objects, tier frontiers", 742, 104, 435)
    d.text("alg3", "3  Resource budget", 445, 150, 306, bold=True)
    d.text("state3", "HBM + path permits + free ACK", 742, 150, 440)
    d.rule("control-rule", 243)
    # Resource boundaries and actual KV buffers, rather than opaque process boxes.
    for key, x, title in [
        ("source", 18, "Source worker"),
        ("peer", 439, "Peer worker"),
        ("store", 860, "Store node"),
    ]:
        d.box(key + "-boundary", "", x, 298, 322, 265, stroke=GRAY)
        d.text(key + "-heading", title, x + 10, 306, 302, bold=True, align="center")
    d.text("primary-label", "GPU / primary KV", 30, 353, 290)
    d.chunks("source-chunks", ["C0", "C1", "C2"], 42, 399, color=INK, cell=78)
    d.text("seal-label", "Seal readable chunks", 33, 458, 280)
    d.text("peer-primary-label", "GPU / primary KV", 449, 352, 302)
    d.chunks("fg-chunks", ["P0", "P1"], 469, 396, color=INK, cell=110)
    d.text("peer-backup-label", "Separate backup HBM", 449, 453, 302, color=BLUE)
    d.chunks("backup-chunks", ["C0", "C1"], 469, 500, color=BLUE, fill=PB, cell=110)
    d.text("store-label", "DRAM prefix objects", 873, 354, 295, color=ORANGE)
    d.chunks("store-chunks", ["C0", "C1"], 891, 399, color=ORANGE, fill=PO, cell=110)
    d.text("store-refs", "C0 / C1 → consumers A, B", 873, 458, 290, h=60, color=ORANGE)
    d.path("admission-permit", [(586, 196), (586, 263), (179, 263), (179, 298)], dashed=True)
    d.path("peer-permit", [(1015, 196), (1015, 277), (600, 277), (600, 298)], dashed=True)
    d.path("copy-peer", [(340, 487), (393, 487), (393, 521), (469, 521)], color=BLUE)
    d.text("copy-peer-label", "Copy", 343, 441, 94, color=BLUE, align="center")
    d.path("copy-dram", [(179, 563), (179, 610), (1021, 610), (1021, 563)], color=ORANGE)
    d.text(
        "copy-dram-label",
        "Independent Source → DRAM copy",
        321,
        609,
        575,
        color=ORANGE,
        align="center",
    )
    d.path("restore-peer", [(754, 520), (791, 520), (791, 416), (701, 416)], color=GREEN)
    d.text("restore-peer-label", "Load", 780, 357, 76, color=GREEN, align="center")
    d.text(
        "path-legend",
        "Worker arrows: solid KV bytes; dashed control. Backups load into primary buffers.",
        18,
        643,
        1164,
        h=34,
        size=26,
    )
    d.write()


def slack():
    example = EXAMPLES["slack"]
    a, b = example["durations_s"].values()
    margin = example["margin_s"]
    assert b - a - margin == 4
    d = Diagram("design-slack-tickets", 530)
    d.text("dag-title", "Residual DAG", 18, 8, 490, bold=True)
    d.text("schedule-title", "Same release; join at 8 s", 620, 8, 560, bold=True)
    for key, txt, x, y, w in [
        ("fork", "Fork", 20, 156, 96),
        ("a", "A\n3 s", 187, 66, 120),
        ("b", "B\n8 s", 187, 252, 120),
        ("join", "Join", 398, 156, 100),
    ]:
        d.box(
            key,
            txt,
            x,
            y,
            w,
            80,
            fill=PG if key in ("a", "b") else "#FFFFFF",
            stroke=GREEN if key in ("a", "b") else INK,
            shape="ellipse" if key in ("fork", "join") else None,
        )
    d.path("fork-a", [(116, 183), (155, 183), (155, 106), (187, 106)])
    d.path("fork-b", [(116, 208), (155, 208), (155, 292), (187, 292)])
    d.path("a-join", [(307, 106), (353, 106), (353, 183), (398, 183)])
    d.path("b-join", [(307, 292), (353, 292), (353, 209), (398, 209)])
    x0, scale = 661, 59
    d.text("a-row", "A", 612, 101, 45, bold=True)
    d.text("b-row", "B", 612, 223, 45, bold=True)
    d.box("a-work", "3 s", x0, 97, 3 * scale, 54, fill=PALE)
    d.box(
        "a-slack",
        "5 s Slack",
        x0 + 3 * scale,
        97,
        5 * scale,
        54,
        fill=PG,
        stroke=GREEN,
        dashed=True,
    )
    d.box("b-work", "8 s", x0, 219, 8 * scale, 54, fill=PALE)
    for t in [0, 3, 8]:
        x = x0 + t * scale
        d.path("tick-" + str(t), [(x, 287), (x, 301)], arrow=False)
        d.text("tick-label-" + str(t), str(t), x - 30, 304, 60, align="center")
    d.path("time", [(x0, 294), (1166, 294)], arrow=True)
    d.path(
        "join-time",
        [(x0 + 8 * scale, 75), (x0 + 8 * scale, 283)],
        color=GREEN,
        dashed=True,
        arrow=False,
    )
    d.text("time-label", "Remaining time (s)", 780, 344, 325, align="center")
    d.rule("ledger-rule", 401)
    d.text("ticket-heading", "Versioned tickets", 18, 415, 293, bold=True)
    d.text("a-ticket", "A: ES=0, LS=5 → Slack=4 s", 314, 415, 553, color=GREEN)
    d.text("b-ticket", "B: Slack=0 s", 910, 415, 277)
    d.text("formula", "Slack = max(LS − ES − m, 0); m = 1 s", 18, 465, 640)
    d.text("ticket-validity", "DAG epoch 7; invalid ticket → 0", 700, 465, 481, color=GRAY)
    d.write()


def shared():
    e = EXAMPLES["prefix"]
    assert e["physical_chunks"] - e["freed_chunks"] == 1
    d = Diagram("design-shared-prefix", 585)
    d.text("logical-title", "Logical consumer views", 18, 8, 500, bold=True)
    d.text("physical-title", "One physical prefix tree", 600, 8, 584, bold=True)
    for i, c in enumerate(["A", "B"]):
        y = 90 + i * 125
        d.text("consumer-" + c, c, 20, y, 55, bold=True)
        d.chunks("view-" + c, ["C0", "C1", "C2-" + c], 90, y, cell=114, height=50, fill=PALE)
        d.text("view-bytes-" + c, "3b", 469, y, 70, align="center")
    d.path("shared-map", [(548, 186), (609, 186)], dashed=True)
    d.box("closure", "", 796, 67, 384, 257, fill=PR, stroke=RED, dashed=True)
    d.text("closure-title", "Deletion closure", 821, 71, 336, color=RED, bold=True, align="center")
    for key, x, y, fill, color in [
        ("C0", 622, 161, PALE, INK),
        ("C1", 813, 161, PR, RED),
        ("C2-A", 1003, 121, PR, RED),
        ("C2-B", 1003, 244, PR, RED),
    ]:
        d.box("tree-" + key, key, x, y, 144, 55, fill=fill, stroke=color)
    d.path("c0-c1", [(766, 188), (813, 188)])
    d.path("c1-ca", [(957, 188), (980, 188), (980, 148), (1003, 148)], color=RED)
    d.path("c1-cb", [(957, 188), (980, 188), (980, 271), (1003, 271)], color=RED)
    d.text("refs", "C0 and C1 are shared by A and B", 596, 341, 586, align="center")
    d.rule("accounting-rule", 399)
    for x, w, title in [
        (18, 405, "Capacity accounting"),
        (454, 340, "Before"),
        (828, 354, "After eviction"),
    ]:
        d.text(
            "account-" + title, title, x, 412, w, bold=True, align="left" if x == 18 else "center"
        )
    d.text("physical-label", "Physical bytes", 18, 456, 420)
    d.text("before-physical", "4b", 454, 456, 340, align="center")
    d.text("after-physical", "b  (3b freed)", 828, 456, 354, align="center", color=RED)
    d.text("logical-label", "Reusable prefix per consumer", 18, 505, 420)
    d.text("before-logical", "A: 3b     B: 3b", 454, 505, 340, align="center")
    d.text("after-logical", "A: b     B: b", 828, 505, 354, align="center", color=RED)
    d.write()


def budget():
    e = EXAMPLES["budget"]
    assert (
        e["fixed_gib"] + e["primary_before_gib"] + e["reserve_gib"] + e["charged_before_gib"] == 40
    )
    assert (
        e["fixed_gib"] + e["primary_after_gib"] + e["reserve_gib"] + e["charged_after_ack_gib"]
        == 40
    )
    d = Diagram("design-foreground-budget", 700)
    d.text("maps-title", "HBM allocation envelope: 40 GiB", 18, 8, 750, bold=True)
    d.text("timeline-title", "Revoke and physical release", 754, 8, 428, bold=True)
    # The middle snapshot continues to charge revoked bytes until the ACK.
    x0, scale = 178, 12.9
    for i, (name, primary, backup) in enumerate(
        [("Before", 12, 6), ("Revoke", 12, 6), ("After ACK", 16, 2)]
    ):
        y = 110 + i * 129
        d.text("map-label-" + str(i), name, 18, y, 154, bold=True)
        offset = 0
        parts = [
            ("Fixed", 16, PALE, INK),
            ("Primary", primary, "#D8DEE5", INK),
            ("Reserve", 6, PG, GREEN),
            ("Peer", backup, PB, BLUE),
        ]
        for j, (label, v, fill, color) in enumerate(parts):
            # Text above segments keeps the narrow Peer region proportional.
            d.box(
                f"map-{i}-{j}", "", x0 + offset * scale, y, v * scale, 54, fill=fill, stroke=color
            )
            d.text(
                f"value-{i}-{j}",
                str(v),
                x0 + offset * scale,
                y,
                v * scale,
                54,
                align="center",
                color=color,
            )
            offset += v
        d.text(
            "peer-charge-" + str(i),
            f"Peer charged: {backup} GiB",
            246,
            y + 61,
            395,
            color=BLUE,
            align="center",
        )
    # Mark the revoked portion within the unchanged physical charge.
    d.box("retiring", "", x0 + 36 * scale, 239, 4 * scale, 54, fill=PR, stroke=RED, dashed=True)
    d.text("pending-demand", "+4 GiB primary waits for free ACK", 18, 508, 698, color=RED)
    for j, (label, color, fill) in enumerate(
        [
            ("Fixed", INK, PALE),
            ("Primary", INK, "#D8DEE5"),
            ("Reserve", GREEN, PG),
            ("Peer", BLUE, PB),
        ]
    ):
        x = 18 + j * 181
        d.box("swatch-" + str(j), "", x, 567, 24, 24, fill=fill, stroke=color)
        d.text("memory-legend-" + str(j), label, x + 32, 558, 147, color=color)
    d.path("timeline", [(798, 77), (798, 522)], arrow=True)
    times = [
        (109, "Primary demand grows", INK),
        (213, "Peer ceiling: 6 → 2 GiB", BLUE),
        (318, "Revoke 4 GiB; charge = 6", RED),
        (423, "Free ACK; charged = 2", GREEN),
    ]
    for i, (y, txt, color) in enumerate(times):
        d.box("event-" + str(i), "", 789, y, 18, 18, fill=color, stroke=color, shape="ellipse")
        d.text("event-label-" + str(i), txt, 824, y - 11, 362, h=69, color=color)
    d.rule("permit-rule", 620)
    d.text(
        "joint-permit",
        "Copy permission also requires: source + destination + link budgets, and a fresh QoS certificate.",
        18,
        634,
        1164,
        h=51,
        size=26,
    )
    d.write()


def commit():
    d = Diagram("commit-tier-timeline", 730)
    d.text("lifecycle-title", "One chunk across independent tiers", 18, 6, 900, bold=True)
    columns = [
        (235, "Seal"),
        (469, "Peer ACK"),
        (703, "Source fails"),
        (938, "Prefix ready"),
        (1140, "Decode"),
    ]
    for i, (x, title) in enumerate(columns):
        d.text(
            "event-label-" + str(i),
            title,
            x - 103,
            53,
            206,
            align="center",
            color=RED if i == 2 else INK,
        )
        d.path(
            "event-line-" + str(i),
            [(x, 100), (x, 344)],
            color=RED if i == 2 else "#CBD1D8",
            dashed=True,
            arrow=False,
            width=1.4,
        )
    for i, label in enumerate(["Source", "Peer HBM", "Store DRAM"]):
        d.text("lane-" + str(i), label, 18, 120 + i * 80, 194, bold=True)
    d.box("readable", "Readable primary C1", 235, 117, 468, 49, fill=PALE)
    d.path("source-end", [(689, 116), (718, 166)], color=RED, arrow=False, width=3)
    d.path("source-end2", [(718, 116), (689, 166)], color=RED, arrow=False, width=3)
    d.box("peer-pending", "Pending", 235, 197, 234, 49, fill="#FFFFFF", stroke=BLUE, dashed=True)
    d.box("peer-committed", "Committed C1 survives", 469, 197, 671, 49, fill=PB, stroke=BLUE)
    d.box(
        "dram-pending", "Pending C1", 235, 277, 468, 49, fill="#FFFFFF", stroke=ORANGE, dashed=True
    )
    d.box("dram-abort", "Aborted", 703, 277, 437, 49, fill=PR, stroke=RED, dashed=True)
    d.rule("failure-snapshot-rule", 375)
    d.text("snapshot-title", "Committed prefix at failure", 18, 392, 556, bold=True)
    d.text("materialize-title", "Recover into a new primary", 627, 392, 555, bold=True)
    for i, (tier, color, fill, states) in enumerate(
        [
            ("Peer", BLUE, PB, ["committed", "committed", "absent"]),
            ("DRAM", ORANGE, PO, ["committed", "aborted", "absent"]),
        ]
    ):
        y = 451 + i * 78
        d.text("prefix-" + tier, tier, 18, y, 122, color=color, bold=True)
        d.chunks(
            "prefix-" + tier,
            ["C0", "C1", "C2"],
            151,
            y,
            cell=107,
            height=50,
            color=color,
            fill=fill,
            states=states,
        )
    d.text("frontier", "Peer frontier = 2; DRAM frontier = 1", 18, 605, 561)
    d.text("backup-label", "Backup", 626, 454, 160, color=BLUE)
    d.chunks("recovery-backup", ["C0", "C1"], 802, 451, cell=151, height=50, color=BLUE, fill=PB)
    d.path("materialize", [(873, 501), (873, 548)], color=GREEN)
    d.text("copy-label", "Copy", 643, 509, 150, color=GREEN, align="center")
    d.text("new-primary", "New primary", 626, 557, 174)
    d.chunks(
        "recovery-primary", ["C0", "C1", "C2"], 802, 550, cell=104, height=50, color=INK, fill=PALE
    )
    d.text("suffix-label", "C2 recomputed before decode resumes", 628, 614, 548, color=RED)
    d.rule("phase-rule", 667)
    d.text(
        "phase-equation",
        "Failure → prefix ready: materialize     |     Prefix ready → decode: suffix + resume",
        18,
        681,
        1164,
        h=38,
    )
    d.write()


BUILDERS = {
    "system-overview": overview,
    "design-slack-tickets": slack,
    "design-shared-prefix": shared,
    "design-foreground-budget": budget,
    "commit-tier-timeline": commit,
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--only", choices=BUILDERS)
    args = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    for name, fn in BUILDERS.items():
        if args.only and name != args.only:
            continue
        fn()
        source = OUT / (name + ".drawio")
        ET.parse(source)
        for ext in ["pdf", "svg", "png"]:
            target = TMP / (name + ".pdf") if ext == "pdf" else OUT / (name + "." + ext)
            cmd = [CLI, "-x", "-f", ext, "-e", "-b", "0", "-o", str(target), str(source)]
            if ext == "pdf":
                cmd.insert(5, "--crop")
            if ext == "png":
                cmd[5:5] = ["-s", "1.5"]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
        with pymupdf.open(TMP / (name + ".pdf")) as src:
            assert len(src) == 1
            dst = pymupdf.open()
            page = dst.new_page(width=504, height=src[0].rect.height * 504 / src[0].rect.width)
            page.show_pdf_page(page.rect, src, 0)
            dst.set_metadata(
                {
                    "title": name,
                    "subject": "AegisKV revision-3 mechanism illustration; not measured data",
                }
            )
            dst.save(OUT / (name + ".pdf"))
            dst.close()
        print(name, flush=True)
    if args.only:
        return
    example_file = OUT / "design-examples.json"
    example_file.write_text(json.dumps(EXAMPLES, indent=2) + "\n")
    records = [
        {
            "name": name,
            "evidence": "design",
            "width_in": 7,
            "files": {
                ext: sha(OUT / (name + "." + ext)) for ext in ["pdf", "svg", "png", "drawio"]
            },
        }
        for name in BUILDERS
    ]
    sources = [
        Path(__file__),
        ROOT / "benchmark/AegisKV/docs/paper/ALGORITHM_REVISION_V3.md",
        example_file,
    ]
    (OUT / "diagrams-manifest.json").write_text(
        json.dumps(
            {
                "schema": "aegiskv.paper_story.diagrams.v2",
                "figures": records,
                "input_bindings": {str(p.relative_to(ROOT)): sha(p) for p in sources},
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
