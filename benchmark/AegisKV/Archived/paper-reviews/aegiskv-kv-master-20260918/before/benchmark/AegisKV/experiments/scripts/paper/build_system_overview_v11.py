"""Mechanism-rich native Draw.io overview, with removable paper annotations.

All miniature DAGs, slack bars, and memory cells are design schematics.
They encode no measurements or deployment capacity ratios.
"""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / "benchmark/AegisKV/paper/figures"
W, H = 1400, 1260
INK, GRAY, BLUE, GOLD, RED = "#243746", "#708391", "#2375A5", "#AA7528", "#B44755"
GREEN, LOCAL, PEER, TAIL = "#7B9F92", "#DCECE5", "#C9E0F0", "#F2D6A8"


class Diagram:
    def __init__(self):
        self.doc = ET.Element("mxfile", host="app.diagrams.net", version="31.1.5")
        page = ET.SubElement(self.doc, "diagram", id="aegiskv-overview-v11", name="System overview")
        model = ET.SubElement(page, "mxGraphModel", page="1", pageScale="1", pageWidth=str(W),
                              pageHeight=str(H), background="#ffffff", grid="1", gridSize="10")
        self.graph = ET.SubElement(model, "root")
        ET.SubElement(self.graph, "mxCell", id="0")
        ET.SubElement(self.graph, "mxCell", id="1", value="Architecture", parent="0")
        ET.SubElement(self.graph, "mxCell", id="annotations", value="Paper annotations", parent="0")
        self.origins = {"1": (0, 0), "annotations": (0, 0)}

    def node(self, ident, value, x, y, w, h, *, parent="1", fill="none", stroke="none",
             font=29, bold=False, align="center", style=""):
        px, py = self.origins[parent]
        base = (f"html=0;whiteSpace=wrap;align={align};verticalAlign=middle;spacing=0;"
                f"fontFamily=Helvetica;fontSize={font};fontColor={INK};"
                f"fillColor={fill};strokeColor={stroke};strokeWidth=1.8;")
        if bold:
            base += "fontStyle=1;"
        c = ET.SubElement(self.graph, "mxCell", id=ident, value=value, vertex="1",
                          parent=parent, style=base+style)
        ET.SubElement(c, "mxGeometry", x=str(x-px), y=str(y-py), width=str(w), height=str(h),
                      **{"as": "geometry"})
        self.origins[ident] = (x, y)
        return ident

    def group(self, ident, x, y, w, h, *, parent="1", fill="none", stroke="none", style=""):
        return self.node(ident, "", x, y, w, h, parent=parent, fill=fill, stroke=stroke,
                         style="container=1;collapsible=0;pointerEvents=0;"+style)

    def edge(self, ident, source, target, *, color=GRAY, dashed=False, both=False,
             exit=(.5, 1), entry=(.5, 0), points=(), width=2.4, arrow="block"):
        style = (f"html=0;rounded=0;strokeColor={color};strokeWidth={width};"
                 f"endArrow={arrow};endSize=9;endFill=1;exitX={exit[0]};exitY={exit[1]};exitPerimeter=0;"
                 f"entryX={entry[0]};entryY={entry[1]};entryPerimeter=0;jumpStyle=arc;jumpSize=8;")
        if dashed:
            style += "dashed=1;dashPattern=6 4;"
        if both:
            style += "startArrow=block;startFill=1;startSize=9;"
        c = ET.SubElement(self.graph, "mxCell", id=ident, edge="1", parent="1", source=source,
                          target=target, style=style)
        geom = ET.SubElement(c, "mxGeometry", relative="1", **{"as": "geometry"})
        if points:
            pts = ET.SubElement(geom, "Array", **{"as": "points"})
            for x, y in points:
                ET.SubElement(pts, "mxPoint", x=str(x), y=str(y))


def build():
    d=Diagram(); n,g,e=d.node,d.group,d.edge
    n("canvas", "", 0, 0, W, H, fill="#ffffff", style="pointerEvents=0;")
    g("applications", 18, 16, 1364, 194, fill="#F3F7FA", stroke="#A5B6C3",
      style="rounded=1;arcSize=6;")
    g("control-plane", 18, 247, 1364, 352, fill="#FAFAFC", stroke="#A5B0BF",
      style="rounded=1;arcSize=4;")
    g("engines", 18, 641, 1364, 605, fill="#F6F8FA", stroke="#A5B6C3",
      style="rounded=1;arcSize=3;")
    # Applications: a concrete request card and a genuine fan-out/join topology.
    n("apps-title", "Applications", 40, 28, 322, 44, parent="applications", font=36, bold=True, align="left")
    g("request", 42, 86, 310, 104, parent="applications", fill="#E8F1F8", stroke="#7FA1BA",
      style="rounded=1;arcSize=7;")
    n("request-title", "LLM request", 61, 94, 270, 35, parent="request", font=31, bold=True, align="left")
    n("request-fields", "Workflow ID\nNode ID", 61, 132, 264, 55, parent="request", align="left")
    n("workflow-title", "Agent runtime · workflow DAG", 457, 26, 815, 44, parent="applications", font=33, bold=True)
    g("workflow",425,73,901,130,parent="applications")
    for ident,label,x,y in [("a0","A0",448,108),("a1","A1",698,75),("a2","A2",698,153),
                            ("a3","A3",948,108),("a4","A4",1194,108)]:
        n(ident,label,x,y,92,47,parent="workflow",fill="#FFFFFF",stroke="#8C9FAB",
          font=29,bold=True,style="rounded=1;arcSize=10;")
    for src,dst in [("a0","a1"),("a0","a2"),("a1","a3"),("a2","a3"),("a3","a4")]:
        e(f"dag-{src}-{dst}",src,dst,exit=(1,.5),entry=(0,.5),width=2)

    # Control-plane ownership is visible, but mechanism miniatures replace box inventories.
    n("control-title","Control plane",40,259,310,44,parent="control-plane",font=36,bold=True,align="left")
    g("router",44,333,281,238,parent="control-plane",fill="#E8F0F6",stroke="#8CA4B8",
      style="rounded=1;arcSize=5;")
    n("router-title","Router",64,343,240,42,parent="router",font=33,bold=True)
    n("router-policy","Load + KV locality",57,394,254,38,parent="router")
    for i,width in [(0,116),(1,66)]:
        y=449+i*57
        n(f"route-dp{i}",f"DP{i}",63,y,78,33,parent="router",bold=True)
        n(f"load-track{i}","",158,y+6,137,22,parent="router",fill="#FFFFFF",stroke="#A9BAC7")
        n(f"load-bar{i}","",159,y+7,width,20,parent="router",fill="#91AEC2")
    g("controller",379,296,977,283,parent="control-plane",fill="#F0F2F8",stroke="#A0A9BB",
      style="rounded=1;arcSize=4;")
    n("controller-title","AegisKV Controller",403,302,690,44,parent="controller",font=35,bold=True,align="left")
    n("control-state","KV directory",1098,308,230,35,parent="controller",font=29)
    n("controller-rule","",402,353,930,1,parent="controller",fill="#B5BCCB")
    g("tracker",412,373,216,187,parent="controller")
    n("tracker-title","Workflow\nTracker",414,374,212,72,parent="tracker",font=31,bold=True)
    for i,width in [(1,38),(2,130)]:
        y=464+(i-1)*48
        n(f"slack-request{i}",f"A{i}",414,y,52,33,parent="tracker")
        n(f"slack-track{i}","",479,y+8,136,17,parent="tracker",fill="#FFFFFF",stroke="#B8BECE")
        n(f"slack-bar{i}","",480,y+9,width,15,parent="tracker",fill="#949CB6")
    g("planner",724,366,326,197,parent="controller",fill="#E0E7F2",
      style="rounded=1;arcSize=5;")
    n("planner-title","KV Manager",740,374,294,72,parent="planner",font=31,bold=True)
    for i,(value,fill,col) in enumerate([("R","#F3F4F6",GRAY),("D","#F7E8D2",GOLD),("P",PEER,BLUE)]):
        n(f"tier-{value}",value,741+i*101,449,87,34,parent="planner",fill=fill,stroke=col,bold=True,
          style="rounded=1;arcSize=8;")
    n("plan-caption","Hot blocks",744,524,287,34,parent="planner")
    for row in range(2):
        for col in range(8):
            selected=(row,col) in {(0,1),(0,4),(1,0),(1,5)}
            n(f"plan-cell-{row}-{col}","",750+col*35,490+row*18,30,14,parent="planner",
              fill=BLUE if selected else "#BCC7D7")
    g("recovery",1113,373,218,190,parent="controller")
    n("recovery-title","Recovery\nManager",1114,374,216,72,parent="recovery",font=31,bold=True)
    n("replica-state","Target DP",1114,450,218,34,parent="recovery")
    n("retry-root","",1218,489,4,4,parent="recovery",fill=RED,style="ellipse;")
    for i,x in enumerate([1122,1248]):
        n(f"retry-r{i}",f"r{i+1}",x,506,74,38,parent="recovery",fill="#FAE8EC",stroke="#C58A93",
          style="rounded=1;arcSize=8;")
        e(f"retry-fork{i}","retry-root",f"retry-r{i}",color=RED,
          points=[(1220,498),(x+37,498)],width=2)
    e("slack-to-plan","tracker","planner",exit=(1,(464.5-373)/187),entry=(0,.50))
    e("target-to-policy","recovery","planner",dashed=True,exit=(0,.50),entry=(1,.50),width=2)
    n("slack-label","Slack",630,417,94,33,parent="controller",font=29)
    e("request-submit","request","router",color=INK,exit=(1,.6),entry=(1,.15),
      points=[(353,148),(353,369)],width=2.8)
    e("metadata","workflow","tracker",dashed=True,exit=(319/901,1),entry=(.5,0),
      points=[(744,227),(369,227),(369,354),(520,354)])
    n("metadata-label","DAG + progress",460,212,258,32,fill="#FFFFFF")

    # Engines: explicit block grids, a smaller remote-replica region, and execution interfaces.
    n("engines-title","Inference engines",40,607,430,43,font=36,bold=True,align="left",fill="#FFFFFF")
    for dp,x in [(0,43),(1,787)]:
        group=f"dp{dp}"
        g(group,x,670,570,438,parent="engines",fill="#FFFFFF",stroke="#889DAD",
          style="rounded=1;arcSize=3;")
        n(f"dp-title{dp}",f"DP{dp}",x+21,680,108,42,parent=group,font=35,bold=True,align="left")
        n(f"engine-label{dp}","LLM engine",x+179,685,255,35,parent=group,font=30,bold=True)
        g(f"adapter{dp}",x+21,738,528,59,parent=group,fill="#EAF0F5",stroke="#95A7B5",
          style="rounded=1;arcSize=6;")
        n(f"adapter-title{dp}","Adapter",x+44,748,170,40,parent=f"adapter{dp}",font=31,bold=True,align="left")
        n(f"adapter-detail{dp}","Peer budget · layers",x+207,752,324,33,parent=f"adapter{dp}")
        g(f"hbm{dp}",x+21,839,528,173,parent=group,fill="#FAFCFD",stroke="#8DA3B2")
        # Mirror the regions so the Peer endpoints face the interconnect.
        localx,peerx=(x+21,x+387) if dp==0 else (x+183,x+21)
        localw,peerw=366,162
        g(f"local{dp}",localx,839,localw,173,parent=f"hbm{dp}",fill="#F5F9F7",stroke=GREEN)
        g(f"peer{dp}",peerx,839,peerw,173,parent=f"hbm{dp}",fill="#EFF6FB",stroke="#6C99B8")
        n(f"local-label{dp}","Local KV",localx+105,845,198,35,parent=f"local{dp}",font=30,bold=True)
        n(f"peer-label{dp}","Peer KV",peerx+5,845,152,35,parent=f"peer{dp}",font=30,bold=True)
        n(f"hbm-label{dp}","HBM",x+23,804,84,32,parent=group,bold=True,align="left")
        for row,label in enumerate(["L1","L2","…","LN"]):
            yy=885+row*30
            n(f"layer-{dp}-{row}",label,localx+7,yy-2,51,27,parent=f"local{dp}",font=29)
            for col in range(8):
                chosen=(row,col) in {(0,1),(0,4),(1,0),(1,5)}
                color=TAIL if col==7 else LOCAL
                border=BLUE if chosen else (GOLD if col==7 else "#BCD1C7")
                n(f"local-cell-{dp}-{row}-{col}","",localx+68+col*35,yy,28,23,
                  parent=f"local{dp}",fill=color,stroke=border,
                  style="strokeWidth=3.5;" if chosen else "strokeWidth=1.2;")
        for row in range(2):
            for col in range(2):
                n(f"peer-cell-{dp}-{row}-{col}","",peerx+18+col*62,885+row*30,49,23,
                  parent=f"peer{dp}",fill=PEER,stroke=BLUE,style="strokeWidth=2;")
        n(f"peer-origin{dp}",f"from DP{1-dp}",peerx+3,956,156,39,parent=f"peer{dp}")
        cx=x+360 if dp==0 else x+20
        g(f"connector{dp}",cx,1046,190,49,parent=group,fill="#FFFFFF",stroke="#859BAA",
          style="rounded=1;arcSize=7;")
        n(f"connector-title{dp}","Connector",cx+3,1051,184,37,parent=f"connector{dp}",font=30,bold=True)
        n(f"transfer-label{dp}","Sealed KV",x+67 if dp==0 else x+296,1055,221,34,
          parent=group,align="left" if dp==0 else "right")
        e(f"local-to-connector{dp}",f"local{dp}",f"connector{dp}",
          exit=(.49,1),entry=(.2 if dp==0 else .8,0),
          points=[(localx+.49*localw,1027),(cx+(38 if dp==0 else 152),1027)],both=True,width=2.3)
        peer_port=.7 if dp==0 else .3
        e(f"connector-to-peer{dp}",f"connector{dp}",f"peer{dp}",color=BLUE,
          exit=((peerx+peer_port*peerw-cx)/190,0),entry=(peer_port,1),width=2.6)
        for region,rx,rw in [("local",localx,localw),("peer",peerx,peerw)]:
            read_port=.5 if region=="local" else .75
            e(f"adapter-{region}{dp}",f"adapter{dp}",f"{region}{dp}",
              exit=((rx+rw*read_port-(x+21))/528,1),entry=(read_port,0),both=True,width=2)
        # KV Manager chooses policy; Adapter controls capacity/layers and invokes Connector.
        controlx=x+562 if dp==0 else x+8
        e(f"adapter-connector{dp}",f"adapter{dp}",f"connector{dp}",dashed=True,
          exit=(1 if dp==0 else 0,.5),entry=(1 if dp==0 else 0,.2),
          points=[(controlx,767.5),(controlx,1055.8)],width=1.9)
    e("dispatch","router","adapter0",color=INK,exit=(0,.68),entry=(0,.5),
      points=[(30,495),(30,767.5)],width=2.8)
    e("plans","planner","adapter1",dashed=True,exit=(.36,1),entry=((940-808)/528,0),
      points=[(841.36,627),(940,627)])
    n("plans-label","Policy",785,616,107,33,fill="#FFFFFF")
    e("status","adapter1","planner",dashed=True,exit=((1245-808)/528,0),entry=(.79,1),
      points=[(1245,623),(981.54,623)])
    n("status-label","Ranks / copies",988,604,248,33,fill="#FFFFFF")
    e("retry","recovery","adapter1",color=RED,dashed=True,exit=(1,.75),entry=(1,.5),
      points=[(1370,515.5),(1370,767.5)])
    n("retry-label","Retry",1250,614,94,34,fill="#FFFFFF",style=f"fontColor={RED};")
    e("peer-transfer","connector0","connector1",color=BLUE,both=True,exit=(1,.5),entry=(0,.5),width=3.6)
    n("peer-transfer-label","Peer copy",622,1019,160,33,style=f"fontColor={BLUE};")
    # Independent DRAM copy/restore from both connectors, never a Peer-to-DRAM cascade.
    g("dram",332,1172,740,66,parent="engines",fill="#FCF3E3",stroke=GOLD,
      style="rounded=1;arcSize=7;")
    n("dram-title","Shared DRAM",352,1185,266,39,parent="dram",font=31,bold=True)
    for col in range(7):
        n(f"dram-cell{col}","",647+col*55,1190,44,28,parent="dram",fill="#EED5AA",stroke="#B3894C")
    e("dram-copy0","connector0","dram",color=GOLD,both=True,exit=(.5,1),entry=((498-332)/740,0),width=3)
    e("dram-copy1","connector1","dram",color=GOLD,both=True,exit=(.5,1),entry=((902-332)/740,0),width=3)
    n("dram-transfer-label","Copy / restore",548,1123,305,34,style=f"fontColor={GOLD};")
    n("selection-key","",51,1138,28,23,parent="engines",fill=LOCAL,stroke=BLUE,style="strokeWidth=3.5;")
    n("selection-legend","Peer selection",92,1132,223,34,parent="engines",align="left")
    n("tail-key","",51,1190,28,23,parent="engines",fill=TAIL,stroke=GOLD)
    n("tail-legend","Active tail",92,1184,218,34,parent="engines",align="left")
    n("control-key0","",1126,1147,4,4,parent="engines")
    n("control-key1","",1190,1147,4,4,parent="engines")
    e("control-key-line","control-key0","control-key1",dashed=True,exit=(1,.5),entry=(0,.5),width=2)
    n("control-legend","Control",1205,1131,137,34,parent="engines",align="left")
    n("retry-key0","",1126,1199,4,4,parent="engines")
    n("retry-key1","",1190,1199,4,4,parent="engines")
    e("retry-key-line","retry-key0","retry-key1",color=RED,dashed=True,exit=(1,.5),entry=(0,.5),width=2)
    n("retry-legend","Retry",1205,1183,137,34,parent="engines",align="left")
    for num,x,y in [(1,393,361),(3,705,350),(2,1094,361),(4,47,722)]:
        n(f"badge{num}",str(num),x,y,42,42,parent="annotations",fill="#141A20",font=31,bold=True,
          style="ellipse;fontColor=#FFFFFF;")
    OUT.mkdir(parents=True,exist_ok=True)
    p=OUT/'system-overview-v11.drawio'
    ET.indent(d.doc,space="  ")
    ET.ElementTree(d.doc).write(p,encoding="utf-8",xml_declaration=True)
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    (OUT/'system-overview-v11.json').write_text(json.dumps({
        'evidence':'logical architecture and mechanism schematic; not data or measured capacity ratios',
        'generator':str(Path(__file__).relative_to(ROOT)), 'generator_sha256':sha(Path(__file__)),
        'source_sha256':sha(p),'canvas':[W,H],'placed_width_in':84.65/25.4,
        'annotations':{'1':'Workflow Tracker','2':'Recovery Manager','3':'KV Manager','4':'DP0 Adapter only'},
        'responsibilities':{'Recovery Manager':'Bind retry target and Peer DP rank at arrival; activate retries after failure',
                            'KV Manager':'Choose backup timing, R/D/P tier, per-layer hot-block candidates and priority',
                            'Adapter':'Control Peer budget and resident layer prefix each window; commit copies and execute recovery'},
        'memory_encoding':'Local cells show layer/block layout; blue outlines are a schematic Peer selection in early layers, gold is an active unsealed tail. Peer cells are copies from the opposite DP.',
        'connector':'execution only; no independent protection or routing decisions',
        'review':'pending native exports and paper-size inspection'
    },indent=2)+'\n')
    print(p)


if __name__=='__main__':
    build()
