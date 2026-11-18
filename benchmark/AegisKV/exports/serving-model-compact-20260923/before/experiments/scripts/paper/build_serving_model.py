#!/usr/bin/env python3
"""Conceptual serving model: unfolded turns, token log, batching and TP state.

All block counts and node placements are schematic. Native Draw.io export is
required. No benchmark values, fault rates or cache hit ratios are represented.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import xml.etree.ElementTree as ET

FONT = 'Linux Libertine O'
INK = '#243746'
EDGE = '#627581'
BLUE = '#347693'
PALE = '#EAF3F8'
PURPLE = '#77638B'
LILAC = '#F0ECF5'
AMBER = '#A27943'
WARM = '#FBF0E0'
WIDTH, HEIGHT = 480, 804


def build(path: Path) -> None:
    mx = ET.Element('mxfile', host='app.diagrams.net', type='device')
    diagram = ET.SubElement(mx, 'diagram', id='serving-model', name='Detailed serving model')
    model = ET.SubElement(diagram, 'mxGraphModel', grid='1', gridSize='10', page='1',
                          pageWidth=str(WIDTH), pageHeight=str(HEIGHT), background='#FFFFFF')
    root = ET.SubElement(model, 'root')
    ET.SubElement(root, 'mxCell', id='0')
    ET.SubElement(root, 'mxCell', id='1', parent='0')

    def shape(ident, value, x, y, w, h, *, fill='#FFFFFF', stroke=EDGE,
              size=20.6, bold=False, extra=''):
        style = (f'rounded=1;arcSize=10;whiteSpace=wrap;html=0;'
                 f'fontFamily={FONT};fontSize={size};fontColor={INK};fontStyle={int(bold)};'
                 f'align=center;verticalAlign=middle;fillColor={fill};strokeColor={stroke};'
                 f'strokeWidth=1.4;spacing=1;{extra}')
        cell = ET.SubElement(root, 'mxCell', id=ident, value=value, style=style, vertex='1', parent='1')
        ET.SubElement(cell, 'mxGeometry', x=str(x), y=str(y), width=str(w), height=str(h),
                      **{'as':'geometry'})

    def text(ident, value, x, y, w, h, **kwargs):
        shape(ident, value, x, y, w, h, fill='none', stroke='none', **kwargs)

    def edge(ident, points, *, dashed=False, arrow='block', color=EDGE, source=None, target=None,
             exit_xy=(1,.5), entry_xy=(0,.5)):
        style = (f'rounded=0;html=0;strokeColor={color};strokeWidth=1.55;'
                 f'endArrow={arrow};endSize=5;endFill=1;dashed={int(dashed)};dashPattern=5 4;')
        attrs = {'id':ident, 'value':'', 'edge':'1', 'parent':'1'}
        if source:
            attrs['source']=source
            style += f'exitX={exit_xy[0]};exitY={exit_xy[1]};exitPerimeter=0;'
        if target:
            attrs['target']=target
            style += f'entryX={entry_xy[0]};entryY={entry_xy[1]};entryPerimeter=0;'
        attrs['style']=style
        cell = ET.SubElement(root, 'mxCell', **attrs)
        geom = ET.SubElement(cell, 'mxGeometry', relative='1', **{'as':'geometry'})
        if not source:
            ET.SubElement(geom, 'mxPoint', x=str(points[0][0]), y=str(points[0][1]), **{'as':'sourcePoint'})
        if not target:
            ET.SubElement(geom, 'mxPoint', x=str(points[-1][0]), y=str(points[-1][1]), **{'as':'targetPoint'})
        if len(points)>2:
            arr = ET.SubElement(geom, 'Array', **{'as':'points'})
            for x,y in points[1:-1]: ET.SubElement(arr, 'mxPoint', x=str(x), y=str(y))

    shape('canvas','',0,0,WIDTH,HEIGHT,stroke='none',extra='rounded=0;')
    text('runtime-title','Workflow runtime',8,4,340,28,size=22,bold=True,extra='align=left;')
    shape('runtime','',6,32,468,219,fill='#F7F9FA',stroke='#A9B5BF')
    text('wf1-title','Workflow 1',12,38,291,26,bold=True)
    text('wf2-title','Workflow 2',324,38,144,26,bold=True)
    # Workflow 1 unfolds a tool-mediated Agent B turn. Workflow 2 remains compact.
    nodes = [
        ('a1','A1',16,98,36,32,'#E2E8EC',EDGE),
        ('b1','B1',78,73,36,32,PALE,BLUE),
        ('tool','Tool',132,73,55,32,WARM,AMBER),
        ('b2','B2',205,73,36,32,PALE,BLUE),
        ('c1','C1',141,125,36,32,PALE,BLUE),
        ('a2','A2',269,98,36,32,'#FFFFFF',EDGE),
        ('d1','D1',328,98,36,32,'#E2E8EC',EDGE),
        ('e1','E1',380,73,36,32,LILAC,PURPLE),
        ('f1','F1',380,125,36,32,LILAC,PURPLE),
        ('d2','D2',432,98,36,32,'#FFFFFF',EDGE),
    ]
    for ident,value,x,y,w,h,fill,stroke in nodes:
        shape(ident,value,x,y,w,h,fill=fill,stroke=stroke,extra='rounded=0;' if ident=='tool' else '')
    paths = [
        ('a-b','a1','b1',[(52,114),(63,114),(63,89),(78,89)]),
        ('a-c','a1','c1',[(52,114),(63,114),(63,141),(141,141)]),
        ('b-tool','b1','tool',[(114,89),(132,89)]),
        ('tool-b2','tool','b2',[(187,89),(205,89)]),
        ('b2-a','b2','a2',[(241,89),(253,89),(253,114),(269,114)]),
        ('c-a','c1','a2',[(177,141),(253,141),(253,114),(269,114)]),
        ('d-e','d1','e1',[(364,114),(372,114),(372,89),(380,89)]),
        ('d-f','d1','f1',[(364,114),(372,114),(372,141),(380,141)]),
        ('e-d','e1','d2',[(416,89),(424,89),(424,114),(432,114)]),
        ('f-d','f1','d2',[(416,141),(424,141),(424,114),(432,114)]),
    ]
    for ident,s,t,p in paths: edge(ident,p,source=s,target=t)
    # Logical token inputs survive outside worker scopes. They are not KV tensors.
    shape('history','',15,174,450,64,fill='#FFFFFF',stroke='#9AAEB9')
    text('history-label','Accepted histories (per agent)',21,176,433,26)
    for ident,value,x,w in [('role','Role/task',20,91),('tokens','Model text',113,113),
                            ('tools','Tool result',228,108),('peer','Agent output',338,122)]:
        shape('history-'+ident,value,x,208,w,26,fill='#F2F5F7',stroke='#A9B5BF',extra='rounded=0;')
    edge('build-request',[(231,238),(231,289)],source='history',exit_xy=(.48,1),
         target='input-prefix',entry_xy=((231-99)/206,0),color=BLUE)
    text('assemble-label','Build next request',16,254,192,26,extra='align=left;')

    # Build a concrete next-turn request, then expose its queue identity.
    text('input-label','B2 input',6,293,88,50,bold=True)
    shape('input-prefix','Cached prefix\nreuse KV',99,291,206,53,fill=PALE,stroke=BLUE,
          extra='rounded=0;')
    shape('input-suffix','New tokens\nprefill',305,291,158,53,fill=WARM,stroke=AMBER,
          extra='rounded=0;')
    edge('input-to-ready',[(226,344),(226,367)],color=BLUE)
    shape('ready-queue','',9,368,455,40,fill='#FFFFFF',stroke='#A7B4BD')
    text('ready-title','Ready requests',14,374,155,27,extra='align=left;')
    for ident,value,x,wf in [('rq-b','W1:B2',174,1),('rq-c','W1:C1',247,1),
                            ('rq-e','W2:E1',320,2),('rq-f','W2:F1',393,2)]:
        shape(ident,value,x,374,68,28,fill=PALE if wf==1 else LILAC,
              stroke=BLUE if wf==1 else PURPLE,extra='rounded=0;')
    edge('queue-to-scheduler',[(242,408),(242,435)],color=BLUE)
    shape('scheduler','',80,435,322,58,fill='#F1F4F6')
    text('scheduler-name','Serving scheduler',88,437,306,27,bold=True)
    text('scheduler-mode','Prefill / decode batching',88,465,306,26)
    # Accepted output is recorded by the runtime; the worker does not own this log.
    edge('accepted-outputs',[(402,450),(478,450),(478,204),(465,204)],dashed=True,
         source='scheduler',exit_xy=(1,.26),target='history',entry_xy=(1,.47))
    text('output-label','Outputs',398,416,77,26)

    # Explicit cross-workflow batches; each TP rank sees the same token positions.
    edge('dispatch0',[(171,493),(171,507),(118,507),(118,540)],color=BLUE,
         source='scheduler',exit_xy=(.28,1),target='worker0',entry_xy=(.5,0))
    edge('dispatch1',[(308,493),(308,507),(362,507),(362,540)],color=BLUE,
         source='scheduler',exit_xy=(.71,1),target='worker1',entry_xy=(.5,0))
    edge('result0',[(214,540),(214,511),(230,511),(230,493)],dashed=True,
         source='worker0',exit_xy=(.93,0),target='scheduler',entry_xy=(.465,1))
    edge('result1',[(448,540),(448,517),(391,517),(391,493)],dashed=True,
         source='worker1',exit_xy=(.90,0),target='scheduler',entry_xy=(.966,1))
    for wi,ox,agents in [(0,8,('B','E')),(1,252,('C','F'))]:
        w=f'worker{wi}'
        shape(w,'',ox,540,220,204,stroke=EDGE,extra='dashed=1;dashPattern=5 4;')
        text(w+'-title',f'Worker {wi}: TP2 replica',ox+4,543,212,27,bold=True)
        for rank,rx in [(0,ox+9),(1,ox+116)]:
            r=f'{w}-rank{rank}'
            shape(r,'',rx,578,95,155,fill='#F6F7F8',stroke='#A0AFB9')
            text(r+'-name',f'Rank {rank}',rx+1,580,93,26)
            shape(r+'-weights','Weights',rx+5,609,85,26,fill='#E3E8EB',stroke='#8798A3',extra='rounded=0;')
            for ai,agent in enumerate(agents):
                y=645+ai*29
                text(r+f'-agent-{agent}',agent,rx+4,y,21,25,bold=True)
                # Three token blocks across two illustrative layers, per agent.
                # The newest block uses warm fill to denote newly appended KV.
                for layer in range(2):
                    for block in range(3):
                        shape(r+f'-{agent}-l{layer}-b{block}','',rx+29+block*18,y+3+layer*10,
                              16,8,fill=WARM if block==2 else (PALE if ai==0 else LILAC),
                              stroke=AMBER if block==2 else (BLUE if ai==0 else PURPLE),
                              extra='rounded=0;strokeWidth=1;')
            text(r+'-table','KV table',rx+1,704,93,26)
    text('kv-semantics','Each KV grid: layers × token blocks',9,750,464,26)
    text('new-kv-label','Rightmost blocks: appended KV',9,777,464,26)

    path.parent.mkdir(parents=True,exist_ok=True)
    ET.indent(mx)
    ET.ElementTree(mx).write(path,encoding='utf-8',xml_declaration=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    build(p.parse_args().output)
