#!/usr/bin/env python3
"""Editable, original architecture illustrations for the revised paper."""
from pathlib import Path
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parents[2] / 'experiments/results/paper/legacy-rendered-figures'
INK = '#263445'
BLUE, ORANGE, GREEN, PURPLE, RED = '#0072B2','#C77700','#008568','#7651A8','#C44747'

class Diagram:
    def __init__(self, name, height):
        self.name = name
        self.file = ET.Element('mxfile',host='app.diagrams.net',version='31.1.5')
        diagram = ET.SubElement(self.file,'diagram',id=name,name=name)
        graph = ET.SubElement(diagram,'mxGraphModel',grid='1',gridSize='10',
            page='1',pageScale='1',pageWidth='1000',pageHeight=str(height),
            background='#FFFFFF',math='0')
        self.root = ET.SubElement(graph,'root')
        ET.SubElement(self.root,'mxCell',id='0')
        ET.SubElement(self.root,'mxCell',id='1',parent='0')
        self.serial = 0

    def node(self, id, text, x,y,w,h, *, color=INK, fill='#FFFFFF',
             parent='1', container=False, label=False, bold=False, size=20):
        style = ('text;strokeColor=none;fillColor=none;align=left;' if label else
                 f'rounded=1;arcSize=10;strokeWidth=2;strokeColor={color};fillColor={fill};')
        style += f'fontFamily=Cantarell;fontSize={size};fontColor={color};whiteSpace=wrap;html=0;'
        style += 'spacing=6;verticalAlign=middle;'
        if bold: style += 'fontStyle=1;'
        if container: style += 'container=1;pointerEvents=0;'
        cell=ET.SubElement(self.root,'mxCell',id=id,value=text,style=style,
                           vertex='1',parent=parent)
        ET.SubElement(cell,'mxGeometry',x=str(x),y=str(y),width=str(w),
                       height=str(h),attrib={'as':'geometry'})

    def edge(self, source,target, *, color=INK,dashed=False,points=(),
             exit=(1,.5),entry=(0,.5),text=''):
        self.serial+=1
        style=(f'edgeStyle=orthogonalEdgeStyle;rounded=0;strokeWidth=2;strokeColor={color};'
               f'endArrow=block;endFill=1;fontFamily=Cantarell;fontSize=20;fontColor={color};'
               f'exitX={exit[0]};exitY={exit[1]};entryX={entry[0]};entryY={entry[1]};'
               'labelBackgroundColor=#FFFFFF;html=0;')
        if dashed:style+='dashed=1;'
        c=ET.SubElement(self.root,'mxCell',id=f'edge{self.serial}',parent='1',
                          source=source,target=target,value=text,edge='1',style=style)
        g=ET.SubElement(c,'mxGeometry',relative='1',attrib={'as':'geometry'})
        if points:
            a=ET.SubElement(g,'Array',attrib={'as':'points'})
            for x,y in points:ET.SubElement(a,'mxPoint',x=str(x),y=str(y))

    def write(self):
        OUT.mkdir(parents=True,exist_ok=True)
        ET.indent(self.file)
        ET.ElementTree(self.file).write(OUT/(self.name+'.drawio'),encoding='utf-8',
                                        xml_declaration=True)

def system():
    d=Diagram('system-overview',570)
    d.node('app','',0,0,1000,110,color=GREEN,fill='#F0F8F5',container=True)
    d.node('apptitle','Application',15,3,200,35,parent='app',label=True,color=GREEN,bold=True,size=22)
    for id,text,x,w in [('events','Observed workflow events',25,240),
                       ('cpm','GBDT + residual-DAG CPM',355,300),
                       ('ticket','Request + Slack ticket',745,230)]:
        d.node(id,text,x,47,w,48,parent='app',color=GREEN)
    d.edge('events','cpm',color=GREEN);d.edge('cpm','ticket',color=GREEN)
    d.node('control','',0,145,1000,150,color=PURPLE,fill='#F6F3FA',container=True)
    d.node('ctitle','Serving control plane',15,3,400,35,parent='control',label=True,color=PURPLE,bold=True,size=22)
    d.node('router','Router / Conductor\nRoute · fence · output',25,47,240,85,parent='control',color=PURPLE)
    d.node('controller','Store Master / KV Directory\nSlackLandlord · recovery queue',355,47,385,85,parent='control',color=PURPLE)
    d.node('aimd','HBMQuotaAIMD\nPublish quota αM',790,47,185,85,parent='control',color=PURPLE)
    d.edge('router','controller',color=PURPLE)
    d.edge('ticket','router',color=GREEN,exit=(.5,1),entry=(0,.5),points=((860,127),(8,127),(8,234)))
    d.node('workers','',0,350,1000,160,color=INK,fill='#FCFCFC',container=True)
    d.node('wtitle','Data plane',15,3,400,35,parent='workers',label=True,bold=True,size=22)
    d.node('source','Source worker\nPrimary KV buffers\nSeal / source copy',25,48,240,95,parent='workers',color=INK)
    d.node('peer','Route-bound target\nPeer-HBM backup\nCopy to primary on recovery',390,48,285,95,parent='workers',color=BLUE,fill='#EAF4FA')
    d.node('store','Mooncake Store\nDRAM backup\nD2H / H2D',790,48,185,95,parent='workers',color=ORANGE,fill='#FFF4E2')
    d.edge('router','source',color=PURPLE,dashed=True,exit=(.5,1),entry=(.5,0))
    d.edge('controller','source',color=PURPLE,dashed=True,exit=(.2,1),entry=(.9,0),points=((432,322),(241,322)))
    d.edge('controller','store',color=PURPLE,dashed=True,exit=(.8,1),entry=(.9,0),points=((663,335),(956,335)))
    d.edge('aimd','peer',color=PURPLE,dashed=True,exit=(.5,1),entry=(.75,0),points=((882,310),(604,310)))
    d.edge('source','peer',color=BLUE,text='HBM copy')
    d.edge('source','store',color=ORANGE,exit=(.5,1),entry=(.5,1),
           points=((145,547),(882,547)),text='Direct DRAM copy · independent ACK')
    d.write()

def commit():
    d=Diagram('commit-recovery',380)
    d.node('title','Example: the source fails after the HBM ACK and before the DRAM ACK',0,0,1000,45,label=True,bold=True,size=22)
    d.node('source','Source\nseals chunk',15,130,170,80)
    d.node('hp','HBM\nPENDING',265,65,185,70,color=BLUE,fill='#EAF4FA')
    d.node('dp','DRAM\nPENDING',265,210,185,70,color=ORANGE,fill='#FFF4E2')
    d.node('hc','HBM\nCOMMITTED',550,65,215,70,color=BLUE,fill='#D4EAF6')
    d.node('da','DRAM\nABORTED',550,210,215,70,color=RED,fill='#FCECEC')
    d.node('recover','Load HBM backup\ninto primary KV;\nrecompute tail',825,110,175,130,color=BLUE,fill='#EAF4FA')
    d.edge('source','hp',color=BLUE,exit=(1,.25),entry=(0,.5),points=((220,150),(220,100)))
    d.edge('source','dp',color=ORANGE,exit=(1,.75),entry=(0,.5),points=((220,190),(220,245)))
    d.edge('hp','hc',color=BLUE,text='all ACKs')
    d.edge('dp','da',color=RED,text='failure')
    d.edge('hc','recover',color=BLUE,exit=(1,.5),entry=(0,.25),points=((795,100),(795,142)))
    d.node('note','Each tier has its own reservation and commit state.\nPending bytes never contribute to a recoverable prefix.',15,310,970,65,label=True)
    d.write()

def motivation():
    d=Diagram('motivation-slack',430)
    d.node('title','Illustrative example: equal KV protection, different workflow benefit',0,0,1000,45,label=True,bold=True,size=22)
    d.node('fork','Fork',10,140,85,65,color=GREEN,fill='#F0F8F5')
    d.node('a','A: 8 s\nSlack = 0 s',135,75,200,90,color=RED,fill='#FCECEC')
    d.node('b','B: 3 s\nSlack = 5 s',135,225,200,90,color=GREEN,fill='#F0F8F5')
    d.node('join','Join',390,140,80,65,color=GREEN,fill='#F0F8F5')
    for branch in ('a','b'):
        d.edge('fork',branch,color=GREEN)
        d.edge(branch,'join',color=GREEN)
    d.node('base','Healthy workflow completion: 8 s',10,350,470,45,label=True)
    d.node('tabletitle','Workflow completion after failure',520,65,480,45,label=True,bold=True)
    for col,(x,w) in enumerate(((520,205),(740,125),(880,115))):
        for row,(y,text,color) in enumerate(((120,('Failed branch','Recompute','Protect')[col],INK),
                (180,('A (critical)','12 s','9 s')[col],RED),
                (240,('B (parallel)','8 s','8 s')[col],GREEN))):
            d.node(f'table{row}{col}',text,x,y,w,45,label=True,color=color)
    d.node('cost','Same request recovery cost: 4 s → 1 s\nWorkflow gain: A saves 3 s; B saves 0 s',520,320,480,80,label=True)
    d.write()

if __name__=='__main__':
    system();commit();motivation()
