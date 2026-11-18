#!/usr/bin/env python3
"""Native diagrams and vector assembly at exactly seven inches paper width."""
import argparse, csv, json, subprocess
from pathlib import Path
import xml.etree.ElementTree as ET
import pymupdf
from figure_style import PAPER, OUT, BLUE, ORANGE, GREEN, PURPLE, RED, GRAY
from paper_paths import DATA, TOOLS, DOCS, BUILD, DELIVERY, TEMPLATE, ARTIFACTS

CLI='/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli'
INK='#243444'

class Diagram:
    def __init__(self, name, height):
        self.name=name
        self.file=ET.Element('mxfile', host='app.diagrams.net', version='31.1.5')
        page=ET.SubElement(self.file,'diagram',id=name,name=name)
        graph=ET.SubElement(page,'mxGraphModel',grid='1',gridSize='10',page='1',
                            pageWidth='1200',pageHeight=str(height),background='#FFFFFF',math='0')
        self.root=ET.SubElement(graph,'root')
        ET.SubElement(self.root,'mxCell',id='0');ET.SubElement(self.root,'mxCell',id='1',parent='0')
        self.node('canvas','',0,0,1200,height,stroke='#FFFFFF')
        self.seq=0

    def node(self,id,text,x,y,w,h,*,parent='1',stroke=INK,fill='#FFFFFF',
             label=False,bold=False,container=False,size=26,align='center',dashed=False):
        style=(f'rounded=0;strokeWidth=1.7;strokeColor={stroke};fillColor={fill};'
               f'fontFamily=Cantarell;fontSize={size};fontColor={stroke};'
               f'whiteSpace=wrap;html=0;align={align};verticalAlign=middle;spacing=4;')
        if label:style+='strokeColor=none;fillColor=none;'
        if bold:style+='fontStyle=1;'
        if container:style+='container=1;pointerEvents=0;'
        if dashed:style+='dashed=1;'
        c=ET.SubElement(self.root,'mxCell',id=id,value=text,style=style,vertex='1',parent=parent)
        ET.SubElement(c,'mxGeometry',x=str(x),y=str(y),width=str(w),height=str(h),attrib={'as':'geometry'})

    def group(self,id,title,x,y,w,h,stroke=INK,fill='#FAFBFC'):
        self.node(id,'',x,y,w,h,stroke=stroke,fill=fill,container=True)
        self.node(id+'-title',title,10,7,w-20,42,parent=id,label=True,bold=True,stroke=stroke)

    def edge(self,id,source,target,*,color=GRAY,exit=(1,.5),entry=(0,.5),points=(),dashed=False,both=False):
        style=(f'edgeStyle=orthogonalEdgeStyle;rounded=0;strokeWidth=2.6;strokeColor={color};'
               f'endArrow=block;endFill=1;exitX={exit[0]};exitY={exit[1]};entryX={entry[0]};entryY={entry[1]};'
               'exitPerimeter=1;entryPerimeter=1;jettySize=10;')
        if dashed:style+='dashed=1;dashPattern=5 4;'
        if both:style+='startArrow=block;startFill=1;'
        c=ET.SubElement(self.root,'mxCell',id=id,edge='1',parent='1',source=source,target=target,style=style)
        g=ET.SubElement(c,'mxGeometry',relative='1',attrib={'as':'geometry'})
        if points:
            arr=ET.SubElement(g,'Array',attrib={'as':'points'})
            for x,y in points:ET.SubElement(arr,'mxPoint',x=str(x),y=str(y))

    def line(self,id,x1,y1,x2,y2,*,color=GRAY,dashed=False,arrow=False):
        style=f'strokeColor={color};strokeWidth=2;endArrow={"block" if arrow else "none"};'
        if dashed:style+='dashed=1;'
        c=ET.SubElement(self.root,'mxCell',id=id,edge='1',parent='1',style=style)
        g=ET.SubElement(c,'mxGeometry',relative='1',attrib={'as':'geometry'})
        ET.SubElement(g,'mxPoint',x=str(x1),y=str(y1),attrib={'as':'sourcePoint'})
        ET.SubElement(g,'mxPoint',x=str(x2),y=str(y2),attrib={'as':'targetPoint'})

    def write(self):
        ET.indent(self.file)
        ET.ElementTree(self.file).write(OUT/(self.name+'.drawio'),encoding='utf-8',xml_declaration=True)

def workflow():
    rows=sorted(csv.DictReader((DATA/'motivation-real-cc/real-cc-example-failure-position.csv').open()),key=lambda r:int(r['branch_index']))
    d=Diagram('motivation-workflow',370)
    d.node('heading','(b) One reconstructed fan-out: branch execution and remaining join slack',0,0,1200,45,label=True,bold=True,align='left')
    to_x=lambda t:150+(t-290)/150*930
    join=float(rows[0]['fanout_completion_s']);fault=float(rows[0]['failure_time_s'])
    for i,r in enumerate(rows):
        start=float(r['branch_start_s']);end=float(r['branch_end_s']);y=80+i*43
        color=RED if i==3 else BLUE
        d.node(f'a{i}',f'A{i+1}',50,y-2,72,37,label=True,bold=True,stroke=color)
        d.node(f'run{i}','',to_x(start),y,to_x(end)-to_x(start),32,stroke=color,fill='#F5DDE0' if i==3 else '#DCECF6')
        if end<join:
            d.node(f'slack{i}','',to_x(end),y,to_x(join)-to_x(end),32,stroke=GREEN,fill='#F0F8F4',dashed=True)
        d.node(f'slack-label{i}',f'{float(r["slack_s"]):.1f} s',1090,y-3,107,40,label=True,stroke=GREEN)
    d.node('slack-label','Slack',1080,42,117,36,label=True,bold=True,stroke=GREEN)
    d.line('join',to_x(join),73,to_x(join),293,color=GREEN)
    d.line('fault',to_x(fault),72,to_x(fault),293,color=RED,dashed=True)
    d.node('fault-label','Fault at 349.5 s',to_x(fault)-128,39,256,36,label=True,stroke=RED)
    d.line('time-axis',150,295,1080,295,arrow=True)
    for t in (300,350,400):
        x=to_x(t);d.line(f'tick{t}',x,290,x,301)
        d.node(f'time{t}',str(t),x-40,298,80,35,label=True)
    d.node('time-label','Observed time from trace start (s)',340,334,630,36,label=True)
    d.write()

def system():
    d=Diagram('system-overview',750)
    d.group('app','Application',0,0,350,165,GREEN,'#F2F8F5')
    d.node('app-body','Observed residual DAG\nAlg. 1: GBDT + CPM\nVersioned Slack ticket',12,60,326,90,parent='app',label=True,stroke=GREEN)
    d.group('router','Aegis Router',405,0,295,165,PURPLE,'#F6F3FA')
    d.node('router-body','Primary / standby\nSharing namespace\nRoute + output fence',10,50,275,108,parent='router',label=True,stroke=PURPLE)
    d.group('master','Mooncake Store Master',750,0,450,330,INK,'#F5F8FB')
    d.node('native','Object directory / placement / RPC',12,50,426,65,parent='master',label=True)
    d.node('controller','',15,123,420,190,parent='master',container=True,stroke=PURPLE,fill='#F6F3FA')
    d.node('controller-title','Policy owner · revision 3',6,4,408,38,parent='controller',label=True,bold=True,stroke=PURPLE)
    d.node('policy','Alg. 2: PrefixAdmission\nGroups / leases / free ACKs\nAlg. 3: ForegroundBudget',6,47,408,132,parent='controller',label=True,stroke=PURPLE)
    d.edge('ticket','app','router',color=PURPLE,dashed=True)
    d.edge('register','router','master',color=PURPLE,dashed=True)
    d.group('source','Source worker',0,275,350,335)
    d.node('engine','vLLM primary KV',16,55,318,47,parent='source',label=True,bold=True)
    for j in range(4):
        d.node(f'primary{j}',str(j),27+j*75,106,70,40,parent='source',stroke=INK,fill='#E8EDF2')
    d.node('gate','Source connector + gate\nSeal → group → stage copy\nIndependent tier frontiers',16,209,318,109,parent='source',stroke=PURPLE,fill='#F6F3FA')
    d.edge('forward','primary1','gate',exit=(.5,1),entry=(.35,0),points=((137,456),(127,456)))
    d.node('forward-label','after forward',150,444,190,34,label=True)
    d.edge('dispatch','router','source',exit=(.15,1),entry=(.5,0),color=PURPLE,dashed=True,points=((449,210),(175,210)))
    d.node('dispatch-label','dispatch',40,220,185,36,label=True,stroke=PURPLE)
    d.edge('admit-ack','controller','gate',exit=(0,.55),entry=(1,.2),color=PURPLE,dashed=True,both=True,points=((383,227),(383,506)))
    d.node('rpc-label','Admit / CompleteCopy',403,224,332,37,label=True,stroke=PURPLE)
    d.group('peer','Bound standby worker',445,375,320,235,BLUE,'#F2F7FB')
    d.node('backup','HBM: backup + staging\n[0] [1] committed',15,55,290,74,parent='peer',stroke=BLUE,fill='#DCECF6')
    d.node('primary','Separate primary KV',15,179,290,45,parent='peer',stroke=INK,fill='#E8EDF2')
    d.edge('load-hbm','backup','primary',exit=(.35,1),entry=(.35,0),color=GREEN)
    d.node('copy-label','load copy',585,517,170,35,label=True,stroke=GREEN)
    d.edge('quota','controller','peer',exit=(0,.9),entry=(.5,0),color=PURPLE,dashed=True,both=True,points=((735,294),(735,345),(605,345)))
    d.node('quota-label','reservations / free ACK',425,301,285,36,label=True,stroke=PURPLE)
    d.group('store','Mooncake Store DRAM',870,405,330,205,ORANGE,'#FFFAF0')
    d.node('objects','Shared prefix objects\n[0] [1] ...\nIndependent tier commit',15,57,300,130,parent='store',stroke=ORANGE,fill='#FFF0D9')
    d.edge('hbm-write','gate','backup',color=BLUE,exit=(1,.75),entry=(0,.6),points=((415,566),(415,474)))
    d.node('hbm-label','HBM copy',330,617,220,37,label=True,stroke=BLUE)
    d.edge('dram-write','gate','objects',color=ORANGE,exit=(.5,1),entry=(.7,1),points=((175,687),(1095,687)))
    d.node('dram-label','Independent DRAM: Source → Store',548,642,526,39,label=True,stroke=ORANGE)
    d.edge('dram-read','objects','primary',color=GREEN,exit=(0,.65),entry=(1,.5),points=((810,547),(810,577)))
    d.node('read-label','load',770,494,94,37,label=True,stroke=GREEN)
    d.node('legend','Solid: KV bytes | Dashed: control | Revision 3: event reference',0,709,1200,40,label=True,align='left')
    d.write()

def commit():
    d=Diagram('commit-recovery',620)
    d.node('a-title','(a) Chunk 1: independent tier state over logical time',0,0,1200,46,label=True,bold=True,align='left')
    for id,text,x,w in [('seal','Seal / reserve',190,220),('ack','HBM ACK',492,170),('fault','Source failure',784,234)]:
        d.node(id+'-label',text,x,54,w,45,label=True,bold=True,stroke=RED if id=='fault' else INK)
    d.line('ack-line',550,101,550,296,color=BLUE,dashed=True)
    d.line('fault-line',855,101,855,296,color=RED,dashed=True)
    for i,text in enumerate(('Source','Peer-HBM','Store DRAM')):
        d.node('row'+str(i),text,0,112+i*65,186,47,label=True,align='left')
    d.node('source-live','KV buffers readable',210,116,645,40,stroke=INK,fill='#E8EDF2')
    d.node('hp','PENDING',265,180,285,42,stroke=BLUE,fill='#EDF5FA',dashed=True)
    d.node('hc','COMMITTED',550,180,625,42,stroke=BLUE,fill='#DCECF6')
    d.node('dp','PENDING',265,246,590,42,stroke=ORANGE,fill='#FFF5E5',dashed=True)
    d.node('da','ABORTED',855,246,320,42,stroke=RED,fill='#F8E7E8')
    d.line('time',210,305,1180,305,arrow=True)
    d.node('time-note','Event order only; intervals are not measured durations',150,311,1050,39,label=True)
    d.node('b-title','(b) Recoverable prefix at failure',0,375,590,44,label=True,bold=True,align='left')
    d.node('c-title','(c) Materialize before replay',630,375,565,44,label=True,bold=True,align='left')
    for row,tier,color in [(0,'HBM',BLUE),(1,'DRAM',ORANGE)]:
        y=439+row*70;d.node(tier+'-label',tier,0,y,128,45,label=True,align='left',stroke=color)
        for j in range(3):
            state='C' if j==0 or row==0 and j==1 else 'X' if row==1 and j==1 else '-'
            d.node(tier+str(j),f'{j}: {state}',145+j*125,y,112,45,
                   stroke=color if state=='C' else RED if state=='X' else GRAY,
                   fill='#DCECF6' if state=='C' and row==0 else '#FFF0D9' if state=='C' else '#FFFFFF',dashed=state!='C')
    d.node('backup-strip','HBM backup: 0, 1',640,440,270,48,stroke=BLUE,fill='#DCECF6')
    d.node('primary-strip','New primary: 0, 1',640,522,270,48,stroke=INK,fill='#E8EDF2')
    d.node('tail','Recompute\nsuffix 2',976,486,211,85,stroke=RED,fill='#F8E7E8')
    d.edge('physical-copy','backup-strip','primary-strip',exit=(.5,1),entry=(.5,0),color=GREEN)
    d.edge('recompute','primary-strip','tail',color=RED)
    d.node('key','C: committed   X: aborted   -: absent; no recovery credit for pending bytes',0,580,1200,40,label=True,align='left')
    d.write()

def export(cli, names=('motivation-workflow','system-overview','commit-recovery')):
    for name in names:
        src=OUT/(name+'.drawio')
        native=OUT/(name+'.native.pdf')
        subprocess.run([cli,'-x','-f','png','-e','-b','0','-s','1.4','-o',str(OUT/(name+'.native.png')),str(src)],check=True)
        subprocess.run([cli,'-x','-f','pdf','-e','--crop','-b','0','-o',str(native),str(src)],check=True)
        with pymupdf.open(native) as inp:
            assert len(inp)==1
            ratio=504/inp[0].rect.width
            doc=pymupdf.open();page=doc.new_page(width=504,height=inp[0].rect.height*ratio)
            page.show_pdf_page(page.rect,inp,0)
            doc.set_metadata({'title':name,'author':'','subject':'Editable Draw.io source accompanies this vector figure.'})
            doc.save(OUT/(name+'.pdf'),garbage=4,deflate=True)
            page.get_pixmap(matrix=pymupdf.Matrix(3,3)).save(OUT/(name+'.png'))
    if 'motivation-workflow' not in names:
        return
    # Preserve the historical three-part argument: observed distribution,
    # reconstructed workflow, and the frozen trace/model counterfactual.
    doc=pymupdf.open();page=doc.new_page(width=504,height=338)
    for filename,rect in [
        ('motivation-panels/observed-gap.pdf',pymupdf.Rect(0,0,244.8,165.6)),
        ('motivation-panels/modeled-harm.pdf',pymupdf.Rect(259.2,0,504,165.6)),
        ('motivation-workflow.pdf',pymupdf.Rect(0,180,504,338))]:
        with pymupdf.open(OUT/filename) as inp:page.show_pdf_page(rect,inp,0)
    doc.set_metadata({'title':'Workflow imbalance and exposed recovery delay','author':''})
    doc.save(OUT/'motivation-real-cc.pdf',garbage=4,deflate=True)
    page.get_pixmap(matrix=pymupdf.Matrix(3,3)).save(OUT/'motivation-real-cc.png')
    (OUT/'motivation-real-cc.svg').write_text(page.get_svg_image(text_as_path=False))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cli',default=CLI);p.add_argument('--xml-only',action='store_true');p.add_argument('--only',choices=('motivation-workflow','system-overview','commit-recovery'));a=p.parse_args()
    functions={'motivation-workflow':workflow,'system-overview':system,'commit-recovery':commit}
    selected=(a.only,) if a.only else tuple(functions)
    for name in selected:functions[name]()
    if not a.xml_only:export(a.cli,selected)

if __name__=='__main__':main()
