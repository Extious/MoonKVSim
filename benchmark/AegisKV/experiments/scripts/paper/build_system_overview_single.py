"""Native, editable single-column arrangement of the v11 architecture.

Retains three tiers, symmetric DP components, and decision/transfer ownership.
No counts, bar lengths, or memory proportions represent measurements.
"""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET
import build_system_overview_v11 as base

base.W, base.H = 700, 1268
ROOT, OUT = base.ROOT, base.OUT
INK, BLUE, GOLD, GRAY, RED = base.INK, base.BLUE, base.GOLD, base.GRAY, base.RED


def build():
    d=base.Diagram(); g,e=d.group,d.edge
    def n(*args, **kw):
        kw['font']=max(31,kw.get('font',31))
        return d.node(*args,**kw)
    n('canvas','',0,0,700,1268,fill='#FFFFFF')
    g('apps',10,10,680,182,fill='#F3F7FA',stroke='#A5B6C3',style='rounded=1;arcSize=5;')
    n('apps-title','Applications',28,18,320,40,parent='apps',font=35,bold=True,align='left')
    g('request',28,68,200,108,parent='apps',fill='#E8F1F8',stroke='#7FA1BA')
    n('request-title','Request',39,70,174,34,parent='request',bold=True)
    n('request-fields','Workflow ID\nNode ID',35,111,186,62,parent='request')
    for ident,label,x,y in [('a0','A0',280,109),('a1','A1',425,68),('a2','A2',425,141),('a3','A3',578,109)]:
        n(ident,label,x,y,64,40,parent='apps',fill='#FFFFFF',stroke='#8C9FAB',style='rounded=1;arcSize=8;')
    for src,dst in [('a0','a1'),('a0','a2'),('a1','a3'),('a2','a3')]:
        e(f'dag-{src}-{dst}',src,dst,exit=(1,.5),entry=(0,.5),width=2)
    n('dag-metadata','DAG + progress',370,193,290,34)

    g('control',10,233,680,430,fill='#FAFAFC',stroke='#A5B0BF',style='rounded=1;arcSize=4;')
    n('control-title','Control\nplane',28,240,235,78,parent='control',font=34,bold=True,align='left')
    g('router',28,329,207,219,parent='control',fill='#E8F0F6',stroke='#8CA4B8')
    n('router-title','Router',44,340,174,38,parent='router',font=33,bold=True)
    n('router-policy','Load + KV\nlocality',34,382,195,70,parent='router')
    for dp,width in [(0,83),(1,44)]:
        y=465+dp*40
        n(f'route-dp{dp}',f'DP{dp}',39,y,75,31,parent='router')
        n(f'load-track{dp}','',124,y+8,95,15,parent='router',fill='#FFFFFF',stroke='#A9BAC7')
        n(f'load-bar{dp}','',125,y+9,width,13,parent='router',fill='#91AEC2')
    g('controller',268,245,407,400,parent='control',fill='#F0F2F8',stroke='#A0A9BB')
    n('controller-title','AegisKV Controller',284,251,375,39,parent='controller',font=32,bold=True)
    g('tracker',289,307,370,90,parent='controller')
    n('tracker-title','Workflow Tracker',300,308,346,39,parent='tracker',bold=True)
    for i,x,w in [(1,299,36),(2,466,102)]:
        n(f'slack-agent{i}',f'A{i}',x,358,46,32,parent='tracker')
        n(f'slack-track{i}','',x+52,369,113,16,parent='tracker',fill='#FFFFFF',stroke='#B8BECE')
        n(f'slack-bar{i}','',x+53,370,w,14,parent='tracker',fill='#949CB6')
    g('planner',289,407,370,117,parent='controller',fill='#E0E7F2')
    n('planner-title','KV Placement\nPlanner',300,409,346,69,parent='planner',bold=True)
    for i,(label,fill,col) in enumerate([('R','#F3F4F6',GRAY),('D','#F7E8D2',GOLD),('P',base.PEER,BLUE)]):
        n(f'tier-{label}',label,300+i*61,488,52,31,parent='planner',fill=fill,stroke=col)
    for row in range(2):
        for col in range(6):
            n(f'plan-{row}-{col}','',501+col*24,488+row*17,19,13,parent='planner',
              fill=BLUE if (row,col) in {(0,1),(0,3),(1,0),(1,4)} else '#BCC7D7')
    e('slack-plan','tracker','planner',exit=(.5,1),entry=(.5,0))
    g('recovery',289,556,370,77,parent='controller')
    n('recovery-title','Recovery Manager',300,556,345,36,parent='recovery',bold=True)
    n('retry-root','',464,594,4,4,parent='recovery',fill=RED,style='ellipse;')
    for i,x in enumerate([363,516]):
        n(f'retry-r{i}',f'r{i+1}',x,603,68,30,parent='recovery',fill='#FAE8EC',stroke='#C58A93')
        e(f'retry-fork{i}','retry-root',f'retry-r{i}',color=RED,points=[(466,600),(x+34,600)],width=2)
    e('submit','request','router',color=INK,exit=(0,.5),entry=(0,.15),points=[(18,122),(18,361.85)],width=2.8)
    e('metadata','a2','tracker',dashed=True,exit=(.5,1),entry=(0,.5),points=[(457,227),(251,227),(251,352)])

    g('engines',10,675,680,544,fill='#F6F8FA',stroke='#A5B6C3',style='rounded=1;arcSize=4;')
    n('engine-title','Inference engines',28,681,388,43,parent='engines',font=34,bold=True,align='left')
    for dp,x in [(0,29),(1,381)]:
        group=f'dp{dp}';g(group,x,736,290,374,parent='engines',fill='#FFFFFF',stroke='#889DAD')
        n(f'dp-title{dp}',f'DP{dp}',x+13,740,99,39,parent=group,font=33,bold=True,align='left')
        g(f'adapter{dp}',x+12,790,266,45,parent=group,fill='#EAF0F5',stroke='#95A7B5')
        n(f'adapter-title{dp}','Adapter',x+26,794,233,36,parent=f'adapter{dp}',bold=True)
        n(f'hbm-label{dp}','HBM',x+99,840,92,36,parent=group,bold=True)
        localx,peerx=(x+12,x+178) if dp==0 else (x+112,x+12)
        for region,rx,rw,fill,stroke in [('local',localx,166,'#F5F9F7',base.GREEN),('peer',peerx,100,'#EFF6FB','#6C99B8')]:
            g(f'{region}{dp}',rx,879,rw,147,parent=group,fill=fill,stroke=stroke)
        n(f'local-label{dp}','Local KV',localx+2,881,162,35,parent=f'local{dp}',bold=True)
        n(f'peer-label{dp}','Peer\nKV',peerx+4,882,92,64,parent=f'peer{dp}',bold=True)
        for row,label in enumerate(['L1','L2','…','LN']):
            yy=918+row*25
            n(f'layer{dp}-{row}',label,localx+2,yy-2,46,26,parent=f'local{dp}')
            for col in range(5):
                chosen=(row,col) in {(0,1),(0,3),(1,0),(1,2)}
                n(f'kv{dp}-{row}-{col}','',localx+50+col*22,yy+1,17,20,parent=f'local{dp}',
                  fill=base.TAIL if col==4 else base.LOCAL,
                  stroke=BLUE if chosen else (GOLD if col==4 else '#BCD1C7'),
                  style='strokeWidth=3;' if chosen else 'strokeWidth=1;')
        for row in range(2):
            for col in range(2):
                n(f'peer-kv{dp}-{row}-{col}','',peerx+13+col*39,956+row*27,28,19,parent=f'peer{dp}',fill=base.PEER,stroke=BLUE)
        cx=x+42
        g(f'connector{dp}',cx,1058,209,43,parent=group,fill='#FFFFFF',stroke='#859BAA')
        n(f'connector-label{dp}','Connector',cx+3,1062,203,35,parent=f'connector{dp}',bold=True)
        for region,rx,rw in [('local',localx,166),('peer',peerx,100)]:
            port=(.3 if region=='local' else .75) if dp==0 else (.75 if region=='local' else .3)
            e(f'read-{region}{dp}',f'adapter{dp}',f'{region}{dp}',exit=((rx+rw*port-(x+12))/266,1),entry=(port,0),both=True,width=2)
            e(f'copy-{region}{dp}',f'connector{dp}',f'{region}{dp}',color=BLUE if region=='peer' else GRAY,
              exit=((rx+rw*.55-cx)/209,0),entry=(.55,1),both=region=='local',width=2)
        outer=x+4 if dp==0 else x+286
        e(f'adapter-connector{dp}',f'adapter{dp}',f'connector{dp}',dashed=True,
          exit=(0 if dp==0 else 1,.5),entry=(0 if dp==0 else 1,.5),points=[(outer,812.5),(outer,1079.5)],width=1.7)
    e('dispatch','router','adapter0',color=INK,exit=(0,.75),entry=(0,.5),points=[(18,493.25),(18,812.5)],width=2.8)
    e('plans-status','planner','adapter1',dashed=True,both=True,exit=(1,.55),entry=(.55,0),
      points=[(678,471.35),(678,688),(539.3,688)],width=2)
    n('plans-label','Plans / state',301,668,257,35,fill='#FFFFFF')
    e('retry','recovery','adapter1',color=RED,dashed=True,exit=(1,.68),entry=(1,.5),points=[(683,608.36),(683,812.5)],width=2.5)
    e('peer-copy','connector0','connector1',color=BLUE,both=True,exit=(1,.5),entry=(0,.5),width=3)
    g('dram',198,1163,306,46,parent='engines',fill='#FCF3E3',stroke=GOLD)
    n('dram-label','Shared DRAM',206,1167,290,36,parent='dram',bold=True)
    for dp in [0,1]:
        x=175.5+352*dp
        e(f'dram{dp}',f'connector{dp}','dram',color=GOLD,both=True,exit=(.5,1),entry=(.2 if dp==0 else .8,0),
          points=[(x,1138),(259.2 if dp==0 else 442.8,1138)],width=2.7)
    for num,x,y in [(1,270,299),(2,270,398),(3,270,544),(4,30,814)]:
        n(f'badge{num}',str(num),x,y,35,35,parent='annotations',fill='#141A20',bold=True,style='ellipse;fontColor=#FFFFFF;')
    # Shift the engine group as a whole; bound edges retain their endpoints.
    d.graph.find("mxCell[@id='engines']/mxGeometry").set('y','713')
    for cell in d.graph.findall('mxCell'):
        if cell.get('edge')=='1':
            for pt in cell.findall('./mxGeometry/Array/mxPoint'):
                if float(pt.get('y'))>=736:pt.set('y',str(float(pt.get('y'))+38))
    # Keep annotation numbering on its own editable layer.
    d.doc.find('diagram').set('id','aegiskv-overview-single-column')
    OUT.mkdir(parents=True,exist_ok=True)
    p=OUT/'system-overview-single.drawio';ET.indent(d.doc,space='  ')
    ET.ElementTree(d.doc).write(p,encoding='utf-8',xml_declaration=True)
    (OUT/'system-overview-single.json').write_text(json.dumps({
        'generator':str(Path(__file__).relative_to(ROOT)),
        'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'source_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
        'canvas':[700,1268],'placement_width_in':3.334,
        'evidence':'schematic; no measured ratios or performance values',
        'parent_revision':'system-overview-v11.drawio',
        'policy':'Planner decides; Adapter invokes; Connector transfers',
        'annotations':{'1':'Workflow Tracker','2':'KV Placement Planner','3':'Recovery Manager','4':'DP0 Adapter only'},
        'review':'pending export'
    },indent=2)+'\n')
    print(p)


if __name__=='__main__':build()
