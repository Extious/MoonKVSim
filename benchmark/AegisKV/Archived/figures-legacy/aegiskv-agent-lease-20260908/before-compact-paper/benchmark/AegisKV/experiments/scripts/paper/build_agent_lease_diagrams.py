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
    d = Diagram("system-overview", 625)
    d.text("workflow", "Workflow", 18, 8, 230, bold=True)
    for key, y, color, fill in [("A", 65, ORANGE, PO), ("B", 140, BLUE, PB)]:
        d.box("dag-"+key, key, 28, y, 64, 48, fill=fill, stroke=color, shape="ellipse")
        d.path("join-"+key, [(92, y+24), (138, y+24), (138, 126), (175, 126)], color=color)
    d.box("join", "Join", 175, 102, 92, 48, fill=PALE)
    d.text("alg1", "1   Request Slack", 323, 8, 450, bold=True)
    d.text("slack", "Agent state; fixed within request", 323, 56, 450, 68)
    d.text("alg2", "2   Agent subleases", 323, 139, 450, bold=True)
    d.text("lease", "Shared objects + releasable tails Q", 323, 184, 490, 44)
    d.text("alg3", "3   Guarded AIMD", 828, 8, 365, bold=True)
    d.text("aimd", "Memory ceiling\n+ forward-step feedback", 828, 58, 355, 85)
    d.path("state", [(267,126),(302,126),(302,89),(323,89)], dashed=True)
    d.path("slack-lease", [(545,121),(545,139)], dashed=True)
    d.rule("r", 252)
    for key, x, label, w in [("source",18,"Source worker",310), ("peer",446,"Peer worker",336), ("store",896,"Store node",286)]:
        d.box(key+"-resource", "", x, 302, w, 248, stroke=GRAY)
        d.box(key+"-head", label, x, 302, w, 46, stroke=GRAY, fill=PALE, bold=True)
    d.text("src-kv", "Primary HBM", 32, 361, 270)
    d.chunks("source-chunks", ["C0","C1","C2"], 42, 410, cell=80, height=47)
    d.text("sealed", "C0 / C1 sealed", 42, 484, 264)
    d.text("peer-primary", "Primary HBM", 459, 354, 290)
    d.chunks("primary", ["P0","P1"], 474, 397, cell=91, height=45)
    d.text("peer-backup", "Backup HBM", 459, 450, 290, color=BLUE)
    d.chunks("backups", ["C0","C1"], 474, 493, cell=91, height=43, color=BLUE, fill=PB)
    d.text("dram", "DRAM", 910, 357, 245, color=ORANGE)
    d.chunks("store-chunks", ["C0","C1"], 921, 410, cell=104, height=47, color=ORANGE, fill=PO)
    d.text("references", "Agent A / B leases\none physical copy", 908, 477, 258, 67, color=ORANGE)
    d.path("admit", [(548,228),(548,273),(176,273),(176,302)], dashed=True)
    d.path("grant", [(1002,143),(1002,286),(619,286),(619,302)], dashed=True)
    d.path("peer-copy", [(328,434),(394,434),(394,515),(474,515)], color=BLUE)
    d.text("copy", "Copy", 332, 386, 107, color=BLUE, align="center")
    d.path("dram-copy", [(176,550),(176,585),(1039,585),(1039,550)], color=ORANGE)
    d.text("dram-copy-label", "Independent Source → DRAM copy", 341, 582, 583, color=ORANGE, align="center")
    d.path("load", [(660,515),(800,515),(800,419),(660,419)], color=GREEN)
    d.text("load-label", "Load", 802, 451, 92, color=GREEN, align="center")
    d.path("legend-data", [(810,175),(865,175)], color=GRAY)
    d.text("legend-data-label", "KV bytes", 874, 154, 300)
    d.path("legend-control", [(810,222),(865,222)], dashed=True)
    d.text("legend-control-label", "Control", 874, 201, 300)
    d.write()


def dag_value():
    d = Diagram("design-joint-wct", 600)
    d.text("title", "Shared chunk x: joint workflow value", 18, 5, 840, bold=True)
    d.box("base-legend", "", 582, 57, 58, 28, fill=PALE)
    d.text("base-label", "Work", 648, 48, 150)
    d.box("rec-legend", "", 804, 57, 58, 28, dashed=True)
    d.text("rec-label", "Recovery", 870, 48, 225)
    start, unit = 316, 53
    states = [("Without x",7,2,12), ("Only A uses x",3,2,12), ("A + B use x",3,0,10)]
    assert [max(3+a,8+b)+2 for _,a,b,_ in states] == [12,12,10]
    for i,(label,ra,rb,wct) in enumerate(states):
        y=112+i*131
        d.text(f"state{i}", label, 18,y+9,249,79,bold=True)
        for agent, duration, recovery, off, color, fill in [("A",3,ra,0,ORANGE,PO),("B",8,rb,56,BLUE,PB)]:
            d.text(f"{i}{agent}",agent,272,y+off,39,42,bold=True,color=color)
            d.box(f"{i}{agent}-work",str(duration),start,y+off,duration*unit,42,fill=fill,stroke=color)
            if recovery:
                d.box(f"{i}{agent}-recovery",str(recovery),start+duration*unit,y+off,recovery*unit,42,stroke=color,dashed=True)
            end=start+(duration+recovery)*unit; join=start+(wct-2)*unit
            if join>end:
                d.path(f"{i}{agent}-wait",[(end,y+off+21),(join,y+off+21)],color=color,arrow=False)
            d.path(f"{i}{agent}-join",[(join,y+off+21),(join,y+49)],color=color,arrow=False)
        d.box(f"join{i}","Join\n2",start+(wct-2)*unit,y+17,2*unit,64,fill=PALE)
        d.text(f"wct{i}",f"{wct} ms",1000,y+26,178,44,bold=True,align="center")
    y=516
    d.path("time",[(start,y),(start+12*unit,y)],arrow=False)
    for t in [0,3,8,10,12]:
        x=start+t*unit
        d.path(f"tick{t}",[(x,y-4),(x,y+5)],arrow=False,width=1.2)
        d.text(f"label{t}",str(t),x-28,y+7,56,34,align="center")
    d.text("unit","ms",973,y+6,77)
    d.text("share","Agent order A → B:   W(A,x) = 0 ms;   W(B,x) = 2 ms;   joint gain = 2 ms",18,560,1164,36)
    d.write()


def subleases():
    d=Diagram("design-agent-subleases",570)
    d.text("title","Shared physical chunks; separate Agent credit",18,5,1164,bold=True)
    d.box("root","R",32,91,91,52,fill=PALE)
    for key,y,color,fill in [("X",63,BLUE,PB),("Y",144,ORANGE,PO)]:
        d.box(key,key,260,y,98,50,fill=fill,stroke=color)
        d.path("r-"+key,[(123,117),(196,117),(196,y+25),(260,y+25)],color=GRAY)
    d.box("Q","",239,50,143,155,dashed=True,stroke=GRAY,fill="none")
    d.text("Q-label","Q = {X, Y}",411,65,411,bold=True)
    d.text("chunk-unit","1 GiB per chunk; credit in ms",411,112,760)
    d.text("root-credit","R: 7 ms, unchanged while internal",411,156,760,color=GRAY)
    d.rule("r",224)
    values=[("Before rent",6,4,2),("Rent: δ = 2 ms/GiB",4.8,3.2,0),("A's next request round",6,3.2,None)]
    for i,(title,a,b,credit_y) in enumerate(values):
        left=18+i*398
        d.text(f"state{i}",title,left,242,370,43,bold=True,align="center")
        bx=left+41; scale=30
        d.text(f"x{i}","X",left,306,39,50,bold=True)
        d.box(f"track{i}","",bx,307,300,48,fill=PALE,stroke="#CAD0D6")
        d.box(f"a{i}",f"A: {a:g}",bx,307,a*scale,48,fill=PO,stroke=ORANGE)
        d.box(f"b{i}",f"B: {b:g}",bx+a*scale,307,b*scale,48,fill=PB,stroke=BLUE)
        d.text(f"total{i}",f"Credit(X) = {a+b:g} ms",left,368,370,40,align="center")
        d.text(f"y{i}","Y",left,428,39,44,bold=True)
        if credit_y:
            d.box(f"ycredit{i}","2",bx,428,credit_y*scale,44,fill=PALE)
        else:
            d.chunks(f"yreleased{i}",["Y"],bx,428,cell=60,height=44,states=["aborted"])
            d.text(f"release{i}","0 → released" if i==1 else "released",bx+78,430,255)
    d.rule("r2",500)
    d.text("renewal","Only A renews: 4.8 → 6; B stays at 3.2. Same-round hits leave credit at 9.2 ms.",18,518,1164,46)
    assert abs(4.8+3.2-8)<1e-9 and abs(6+3.2-9.2)<1e-9
    d.write()


def admission():
    d=Diagram("design-prefix-admission",584)
    d.text("title","One physical prefix tree through release and copy",18,5,1164,bold=True)
    states=[("Committed", "committed",None),("Free ACK; x pending","aborted","pending"),("Copy ACK; x readable",None,"committed")]
    for i,(title,a2,new) in enumerate(states):
        x=18+398*i
        d.text(f"head{i}",title,x,64,370,43,bold=True,align="center")
        d.box(f"r{i}","R",x+4,218,68,50,fill=PALE)
        for branch,y,color,fill in [("A",153,ORANGE,PO),("B",299,BLUE,PB)]:
            d.text(f"label{i}{branch}","Agent "+branch,x+113,y-43,248,color=color)
            d.box(f"{i}{branch}1",branch+"1",x+114,y,87,50,fill=fill,stroke=color)
            d.path(f"fork{i}{branch}",[(x+72,243),(x+93,243),(x+93,y+25),(x+114,y+25)],color=color)
        if a2:
            d.chunks(f"a2-{i}",["A2"],x+265,153,cell=88,height=50,color=ORANGE,fill=PO,states=[a2])
            d.path(f"a-edge{i}",[(x+201,178),(x+265,178)],color=ORANGE,dashed=i==1)
        if new:
            d.chunks(f"x-{i}",["x"],x+265,299,cell=88,height=50,color=BLUE,fill=PB,states=[new])
            d.path(f"x-edge{i}",[(x+201,324),(x+265,324)],color=BLUE,dashed=new=="pending")
        d.text(f"readable{i}",["Readable: R, A1, A2, B1","Readable: R, A1, B1","Readable: R, A1, B1, x"][i],x,365,370,42,align="center")
    d.text("initial-tails","Q = {A2, B1}",18,410,370,37,align="center",color=GRAY)
    d.rule("r",452)
    d.text("free-gate","Free space: G(x) ≥ 0",18,465,492,43)
    d.text("replace-gate","Replacement: G(x) > D(victims)",541,465,641,43)
    d.path("events",[(40,548),(1160,548)],color=GRAY)
    for key,x,label in [("v",37,"Validate versions"),("f",438,"Release → free ACK"),("c",850,"Copy → copy ACK")]:
        d.path(key+"-tick",[(x+150,541),(x+150,555)],color=GRAY,arrow=False)
        d.text(key+"-event",label,x,511,330,34,align="center")
    d.write()


def budget():
    d=Diagram("design-guarded-aimd",670)
    d.text("title","Independent Guarded AIMD: permission and physical occupancy",18,5,1164,bold=True)
    d.text("device","40 GiB device",18,56,390,bold=True)
    parts=[("Fixed\n16",16,GRAY,PALE),("Foreground\n14",14,INK,"#D8DDE2"),("Reserve\n4",4,GREEN,PG),("Backup\n4",4,BLUE,PB),("Free\n2",2,ORANGE,PO)]
    x=24
    for i,(label,gib,color,fill) in enumerate(parts):
        d.box(f"memory{i}",label,x,104,gib*28.8,94,fill=fill,stroke=color);x+=gib*28.8
    d.text("initial","Initial: ceiling C = 6 GiB; permission Q = 4 GiB; physical copies = 4 GiB",18,210,1164,48)
    d.rule("r",277)
    scenarios=[("Stable + demand",6,5,4,GREEN),("Forward-step warning",6,2,4,RED),("Next foreground\nneeds +4 GiB",2,2,4,BLUE)]
    for i,(title,c,q,used,color) in enumerate(scenarios):
        left=18+398*i
        d.text(f"head{i}",title,left,291,370,70,bold=True,align="center")
        for j,(label,value,fill,stroke) in enumerate([("C",c,PALE,GRAY),("Q",q,PG if i==0 else PB,color),("Used",used,PB,BLUE)]):
            y=382+j*52; bx=left+88
            d.text(f"label{i}{j}",label,left,y-2,88,44,bold=j==1)
            d.box(f"base{i}{j}","",bx,y,240,37,fill="#F8F9FA",stroke="#CAD0D6")
            d.box(f"bar{i}{j}",str(value),bx,y,value*40,37,fill=fill,stroke=stroke)
        d.text(f"condition{i}",[
            "4 valid windows; demand;\nprior release complete",
            "β = 0.5; stop new copies\nuntil charged bytes ≤ Q",
            "Used: 4 → 2 GiB only\nafter physical free ACK"][i],left,555,370,80,align="center")
    d.text("unit","GiB",18,636,1164,32,align="right")
    assert sum(part[1] for part in parts)==40 and 40-16-14-4==6
    assert 40-16-(14+4)-4==2
    d.write()


def commit():
    d=Diagram("commit-tier-timeline",635)
    d.text("title","Same chunk C1; independent commit boundaries",18,5,1164,bold=True)
    xs=[230,432,657,894,1106]
    labels=["Seal C1","Peer ACK","Source fails","Prefix loaded","Decode"]
    for i,(x,label) in enumerate(zip(xs,labels)):
        d.text(f"event{i}",label,x-91,59,182,58,bold=True,align="center")
        d.path(f"event-line{i}",[(x,128),(x,337)],color=RED if i==2 else "#CAD0D6",dashed=i==2,arrow=False,width=1.5)
    for j,(label,color) in enumerate([("Source",INK),("Peer HBM",BLUE),("Store DRAM",ORANGE)]):
        y=158+j*73
        d.text(f"row{j}",label,18,y-22,183,44,color=color,bold=True)
        d.path(f"lane{j}",[(206,y),(1173,y)],color="#CAD0D6",arrow=False,width=1.2)
    d.box("source-c1","C1 readable",230,136,427,44,fill=PALE)
    d.box("peer-pending","Pending",230,209,202,44,stroke=BLUE,dashed=True)
    d.box("peer-committed","C1 committed",432,209,741,44,stroke=BLUE,fill=PB)
    d.box("dram-pending","C1 pending",230,282,427,44,stroke=ORANGE,dashed=True)
    d.chunks("dram-abort",["C1"],686,282,cell=83,height=44,states=["aborted"],color=ORANGE)
    d.text("abort-label","Aborted",780,285,214,color=RED)
    d.rule("r",359)
    d.text("available","At failure",18,378,320,bold=True)
    d.text("new-primary","New primary before decode",655,378,528,bold=True)
    d.text("peer-label","Peer",18,432,143,color=BLUE)
    d.chunks("peer-prefix",["C0","C1"],164,432,cell=96,height=48,color=BLUE,fill=PB)
    d.text("dram-label","DRAM",18,505,143,color=ORANGE)
    d.chunks("dram-prefix",["C0"],164,505,cell=96,height=48,color=ORANGE,fill=PO)
    d.text("missing","C2 missing",283,508,270,color=GRAY)
    d.path("restore",[(381,456),(520,456),(520,473),(661,473)],color=BLUE)
    d.text("load-label","Load prefix",401,398,224,color=BLUE,align="center")
    d.chunks("materialized",["C0","C1"],661,449,cell=126,height=48,color=BLUE,fill=PB)
    d.chunks("suffix",["C2"],950,449,cell=155,height=48,color=GREEN,fill=PG)
    d.text("prefix-label","Materialized",660,517,265,48,align="center",color=BLUE)
    d.text("suffix-label","Recomputed",929,517,242,48,align="center",color=GREEN)
    d.path("load-phase",[(657,588),(894,588)],color=BLUE,arrow=False)
    d.path("recompute-phase",[(902,588),(1170,588)],color=GREEN,arrow=False)
    d.text("load-phase-label","Load + queue",657,593,245,35,color=BLUE,align="center")
    d.text("recompute-phase-label","Suffix + queue",902,593,279,35,color=GREEN,align="center")
    d.write()


def main():
    native.OUT = OUT
    OUT.mkdir(parents=True, exist_ok=True); TMP.mkdir(parents=True, exist_ok=True)
    builders = {"system-overview": overview, "design-joint-wct": dag_value,
        "design-agent-subleases": subleases, "design-prefix-admission": admission,
        "design-guarded-aimd": budget, "commit-tier-timeline": commit}
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
