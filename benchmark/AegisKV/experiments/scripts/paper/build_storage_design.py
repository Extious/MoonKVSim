#!/usr/bin/env python3
"""Editable mechanism figures for the DRAM/SSD AegisKV design.

All numbers and block identities in these diagrams are constructed examples.
Native Draw.io exports, not this generator, are the rendering authority.
"""
from pathlib import Path
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parents[3]
OUT = BASE / 'exports/system-design-dram-ssd-20260920'
INK, LINE = '#243746', '#70808A'
BLUE, PALE = '#23688D', '#DDEBF3'
ORANGE, SAND = '#9B6428', '#F3E5D1'
GREEN, MINT = '#39756A', '#E1EEE8'
GRAY, WHITE = '#F1F3F4', '#FFFFFF'


class Diagram:
    def __init__(self, name, width, height):
        self.name = name
        self.doc = ET.Element('mxfile', host='app.diagrams.net', version='31.1.5')
        page = ET.SubElement(self.doc, 'diagram', id=name, name=name)
        model = ET.SubElement(page, 'mxGraphModel', page='1', pageScale='1',
                              pageWidth=str(width), pageHeight=str(height), background=WHITE)
        self.root = ET.SubElement(model, 'root')
        ET.SubElement(self.root, 'mxCell', id='0')
        ET.SubElement(self.root, 'mxCell', id='1', parent='0', value='Mechanism')
        self.origins = {'1': (0, 0)}
        self.node('canvas', '', 0, 0, width, height, fill=WHITE)

    def node(self, ident, label, x, y, w, h, *, fill='none', stroke='none',
             font=21, bold=False, align='center', parent='1', extra=''):
        px, py = self.origins[parent]
        style = (f'html=0;whiteSpace=wrap;align={align};verticalAlign=middle;spacing=1;'
                 f'fontFamily=Helvetica;fontSize={font};fontColor={INK};'
                 f'fillColor={fill};strokeColor={stroke};strokeWidth=1.4;'
                 + ('fontStyle=1;' if bold else '') + extra)
        cell = ET.SubElement(self.root, 'mxCell', id=ident, value=label, style=style,
                             vertex='1', parent=parent)
        ET.SubElement(cell, 'mxGeometry', x=str(x-px), y=str(y-py), width=str(w), height=str(h),
                      **{'as': 'geometry'})
        self.origins[ident] = (x, y)
        return ident

    def group(self, ident, x, y, w, h, *, fill=WHITE, stroke=LINE, parent='1'):
        return self.node(ident, '', x, y, w, h, fill=fill, stroke=stroke, parent=parent,
                         extra='container=1;collapsible=0;pointerEvents=0;')

    def edge(self, ident, source, target, *, start=(.5, 1), end=(.5, 0),
             points=(), dashed=False, both=False, color=INK, arrow='block'):
        style = (f'rounded=0;strokeColor={color};strokeWidth=1.7;endArrow={arrow};endFill=1;'
                 f'endSize=5;exitX={start[0]};exitY={start[1]};exitPerimeter=0;'
                 f'entryX={end[0]};entryY={end[1]};entryPerimeter=0;'
                 + ('dashed=1;dashPattern=5 4;' if dashed else '')
                 + ('startArrow=block;startFill=1;startSize=5;' if both else ''))
        cell = ET.SubElement(self.root, 'mxCell', id=ident, style=style, edge='1',
                             parent='1', source=source, target=target)
        g = ET.SubElement(cell, 'mxGeometry', relative='1', **{'as': 'geometry'})
        if points:
            a = ET.SubElement(g, 'Array', **{'as': 'points'})
            for x, y in points:
                ET.SubElement(a, 'mxPoint', x=str(x), y=str(y))

    def save(self):
        (OUT/'sources').mkdir(parents=True, exist_ok=True)
        path = OUT/'sources'/f'{self.name}.drawio'
        ET.indent(self.doc)
        ET.ElementTree(self.doc).write(path, encoding='utf-8', xml_declaration=True)
        return path


def overview():
    d=Diagram('system-overview',480,800); n,g,e=d.node,d.group,d.edge
    g('app',10,10,460,134,fill=GRAY)
    n('app-title','Agent workflow',25,17,430,28,bold=True,parent='app')
    for key,label,x,y in [('a','A',40,81),('b','B',175,57),('c','C',175,104),('join','Join',350,81)]:
        n(key,label,x,y,70,29,fill=WHITE,stroke=LINE,parent='app')
    for key,src,dst in [('ab','a','b'),('ac','a','c'),('bj','b','join'),('cj','c','join')]:
        e(key,src,dst,start=(1,.5),end=(0,.5),color=LINE)
    g('ctrl',10,142,460,208,fill='#FAFBFC')
    n('ctrl-title','Control and surviving metadata',22,147,436,30,bold=True,parent='ctrl')
    n('tracker','Tracker\nDAG + Slack',30,190,160,63,fill=MINT,stroke=GREEN,parent='ctrl')
    n('master','KV Master\nValue + rent',272,190,174,63,fill=PALE,stroke=BLUE,parent='ctrl')
    n('router','Router\nDispatch / retry',30,278,180,60,fill=WHITE,stroke=LINE,parent='ctrl')
    n('directory','Directory\nValid copies',272,278,174,60,fill=WHITE,stroke=LINE,parent='ctrl')
    e('progress','app','tracker',start=(.05,1),end=(0,.5),dashed=True,
      points=[(18,160),(18,221.5)])
    e('slack','tracker','master',start=(1,.5),end=(0,.5),dashed=True)
    e('plan-dir','master','directory',dashed=True)
    e('dir-route','directory','router',start=(0,.5),end=(1,.5),dashed=True)
    g('compute',10,382,460,160,fill=GRAY)
    for i,x in enumerate([27,263]):
        group=f'dp{i}';g(group,x,395,190,132,fill=WHITE,parent='compute')
        n(f'dpt{i}',f'DP {i}',x+7,399,176,25,bold=True,parent=group)
        n(f'hbm{i}','Execution HBM',x+7,431,176,26,fill=MINT,parent=group)
        n(f'adapter{i}','Adapter / copy',x+7,483,176,27,parent=group)
        e(f'local{i}',f'hbm{i}',f'adapter{i}',both=True,color=BLUE)
    e('dispatch0','router','dpt0',start=(.5,1),end=(.5,0),dashed=True,
      points=[(120,365),(122,365)])
    e('dispatch1','router','dpt1',start=(.87,1),end=(.5,0),dashed=True,
      points=[(186.6,365),(358,365)])
    g('store',10,566,460,127,fill='#FAFBFC')
    n('dram','Shared DRAM',35,579,190,41,fill=PALE,stroke=BLUE,parent='store')
    n('ssd','SSD / storage',35,642,190,36,fill=SAND,stroke=ORANGE,parent='store')
    n('fast-state','Retain useful KV',245,583,205,32,parent='store')
    n('capacity-state','Preserve history',245,644,205,32,parent='store')
    e('demote','dram','ssd',both=True,color=BLUE)
    for i,port in enumerate([.3,.8]):
        e(f'copy{i}',f'adapter{i}','dram',start=(.5,1),end=(port,0),both=True,color=BLUE,
          points=[(122 if i==0 else 358,545),(35+190*port,545)])
    # Plan control follows the outer margin, away from all physical byte paths.
    e('placement','directory','store',start=(1,.5),end=(1,.45),dashed=True,
      points=[(477,308),(477,623.15)])
    n('legend','Solid: KV     Dashed: control',15,720,450,26,font=21)
    # Increase space below the workflow without reducing publication-size type.
    for cell in d.root.findall('mxCell'):
        geom=cell.find('mxGeometry')
        if geom is None:continue
        if cell.get('vertex')=='1' and cell.get('parent')=='1' and cell.get('id')!='canvas':
            y=float(geom.get('y','0'))
            if y>=142:geom.set('y',str(y+40))
        if cell.get('edge')=='1':
            for point in geom.findall('.//mxPoint'):
                y=float(point.get('y','0'))
                if y>=142:point.set('y',str(y+40))
    return d.save()


def sparse():
    d=Diagram('sparse-recovery',960,320);n,g,e=d.node,d.group,d.edge
    n('title-a','(a) Full checkpoint, mixed residency',10,5,452,34,font=22,bold=True)
    n('title-b','(b) Prediction never removes KV',500,5,450,34,font=22,bold=True)
    n('prefix','Sealed history M',109,45,286,30)
    n('tail-head','Tail N',400,45,63,30)
    for c in range(5):
        n(f'col{c}',f'B{c}',112+c*55,77,47,29)
    dram={(0,0),(0,3),(1,0),(1,2),(2,0)}
    for r in range(3):
        yy=119+r*46
        n(f'layer{r}',f'Layer {r+1}',8,yy,100,33,align='left')
        for c in range(5):
            here=(r,c) in dram
            n(f'kv{r}{c}','D' if here else 'S',113+c*55,yy,44,31,
              fill=PALE if here else SAND,stroke=BLUE if here else ORANGE)
        n(f'tail{r}','',410,yy,38,31,fill=WHITE,stroke=LINE,extra='dashed=1;')
    n('dram-key','D: DRAM',12,268,112,29,fill=PALE,stroke=BLUE)
    n('ssd-key','S: SSD',138,268,88,29,fill=SAND,stroke=ORANGE)
    n('tail-key','Dashed: replay tail',234,265,230,35)
    n('layer-b','One layer; native selected blocks',497,47,450,29)
    n('predict-title','Predict',503,97,112,35,align='left')
    n('actual-title','Actual',503,148,112,35,align='left')
    for row,chosen in [('p',{0,3}),('q',{0,2})]:
        y=99 if row=='p' else 151
        for c in range(5):
            missed=row=='q' and c==2
            n(f'{row}{c}',f'B{c}',623+c*62,y,52,32,
              fill=SAND if missed else (PALE if c in chosen else WHITE),
              stroke=ORANGE if missed else (BLUE if c in chosen else LINE),bold=c in chosen,
              extra='strokeWidth=2.2;' if c in chosen else '')
    n('miss','B2: fetch from SSD',572,209,325,35,fill=SAND,stroke=ORANGE)
    e('miss-path','miss','q2',start=(.54,0),end=(.5,1),color=ORANGE)
    n('causal','At query q(M+1), fetch misses\nbefore dependent attention executes.',503,263,439,48)
    return d.save()


def rental():
    d=Diagram('rental-competition',960,330);n,g,e=d.node,d.group,d.edge
    n('heading','An illustrative DRAM competition: 1 unit of space required',10,6,940,34,font=22,bold=True)
    columns=[('x','Candidate x',18,6,False),('y','Resident y',253,2,True),
             ('z','Resident z',488,5,True),('q','Pinned reader',723,1,False)]
    for key,label,x,c,eligible in columns:
        g(key,x,63,217,146,fill=WHITE)
        n(key+'t',label,x+5,70,207,31,bold=True,parent=key)
        n(key+'b','Size = 1 unit',x+5,109,207,27,parent=key)
        credit_label='Credit: 1 → 0' if key=='q' else f'Credit = {c}'
        n(key+'c',credit_label,x+5,143,207,30,fill=PALE if key=='x' else GRAY,parent=key)
        n(key+'q','In Q' if eligible else ('Trial only' if key=='x' else 'Outside Q'),
          x+5,177,207,27,parent=key)
    n('rent','Trial rent +2 per unit',19,225,282,36,fill=GRAY,stroke=LINE)
    for key,label,x in [('xb','x: 4 remains',322),('yb','y: 0; propose',535),('zb','z: 3 remains',748)]:
        n(key,label,x,227,194,34,fill=SAND if key=='yb' else PALE,
          stroke=ORANGE if key=='yb' else BLUE)
    n('bottom','Revalue the full replacement plan; commit lower copy before freeing y.',10,282,940,35)
    return d.save()


def lifecycle():
    d=Diagram('checkpoint-lifecycle',960,445);n,g,e=d.node,d.group,d.edge
    n('ha','(a) Copy completion does not imply a new checkpoint',10,5,940,32,font=22,bold=True)
    for j,(lab,x) in enumerate([('Old manifest',15),('New copies',328),('New manifest',641)]):
        g(f's{j}',x,55,300,130,fill=WHITE)
        n(f'st{j}',lab,x+5,61,290,31,bold=True,parent=f's{j}')
        text=['M = 128\nDependencies complete','129..192 pending\nM stays 128','Dependencies complete\nM = 192'][j]
        n(f'sv{j}',text,x+8,108,284,66,fill=PALE if j!=1 else SAND,parent=f's{j}')
    e('old-new','s0','s1',start=(1,.5),end=(0,.5))
    e('new-commit','s1','s2',start=(1,.5),end=(0,.5))
    n('hb','(b) DRAM-to-SSD demotion preserves the same logical object',10,202,940,32,font=22,bold=True)
    xs=[15,252,489,726];labels=['Copy to SSD','Commit + redirect','Drain old readers','Free DRAM']
    for j,(x,lab) in enumerate(zip(xs,labels)):
        n(f'd{j}',lab,x,262,213,45,fill=SAND if j<2 else MINT,
          stroke=ORANGE if j<2 else GREEN)
        if j:e(f'de{j}',f'd{j-1}',f'd{j}',start=(1,.5),end=(0,.5))
    n('hc','(c) Last-copy removal changes the advertised recovery path',10,329,940,32,font=22,bold=True)
    for j,(x,lab) in enumerate(zip(xs,['Validate fallback','Publish fallback','Drain old readers','Delete SSD KV'])):
        n(f'f{j}',lab,x,382,213,45,fill=WHITE,stroke=LINE)
        if j:e(f'fe{j}',f'f{j-1}',f'f{j}',start=(1,.5),end=(0,.5))
    return d.save()


if __name__=='__main__':
    for fn in [overview,sparse,rental,lifecycle]:
        print(fn())
