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
WIDTH, HEIGHT = 520, 535


def build(path: Path) -> None:
    mx = ET.Element('mxfile', host='app.diagrams.net', type='device')
    diagram = ET.SubElement(mx, 'diagram', id='serving-model', name='Detailed serving model')
    model = ET.SubElement(diagram, 'mxGraphModel', grid='1', gridSize='10', page='1',
                          pageWidth=str(WIDTH), pageHeight=str(HEIGHT), background='#FFFFFF')
    root = ET.SubElement(model, 'root')
    ET.SubElement(root, 'mxCell', id='0')
    ET.SubElement(root, 'mxCell', id='1', parent='0')

    def shape(ident, value, x, y, w, h, *, fill='#FFFFFF', stroke=EDGE,
              size=22.6, bold=False, extra=''):
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
    text('runtime-title','Workflow runtime',8,4,410,28,size=23.5,bold=True,extra='align=left;')
    shape('runtime','',6,32,488,116,fill='#F7F9FA',stroke='#A9B5BF')
    text('wf1-title','Workflow 1',12,34,291,26,bold=True)
    text('wf2-title','Workflow 2',324,34,164,26,bold=True)
    # The graph depicts invocation dependencies, not elapsed time.
    nodes = [
        ('a1','A1',16,88,36,32,'#E2E8EC',EDGE),
        ('b1','B1',78,64,36,32,PALE,BLUE),
        ('tool','Tool',132,64,55,32,WARM,AMBER),
        ('b2','B2',205,64,36,32,PALE,BLUE),
        ('c1','C1',141,110,36,32,PALE,BLUE),
        ('a2','A2',269,88,36,32,'#FFFFFF',EDGE),
        ('d1','D1',328,88,36,32,'#E2E8EC',EDGE),
        ('e1','E1',389,64,36,32,LILAC,PURPLE),
        ('f1','F1',389,110,36,32,LILAC,PURPLE),
        ('d2','D2',449,88,36,32,'#FFFFFF',EDGE),
    ]
    for ident,value,x,y,w,h,fill,stroke in nodes:
        shape(ident,value,x,y,w,h,fill=fill,stroke=stroke,extra='rounded=0;' if ident=='tool' else '')
    paths = [
        ('a-b','a1','b1',[(52,104),(63,104),(63,80),(78,80)]),
        ('a-c','a1','c1',[(52,104),(63,104),(63,126),(141,126)]),
        ('b-tool','b1','tool',[(114,80),(132,80)]),
        ('tool-b2','tool','b2',[(187,80),(205,80)]),
        ('b2-a','b2','a2',[(241,80),(253,80),(253,104),(269,104)]),
        ('c-a','c1','a2',[(177,126),(253,126),(253,104),(269,104)]),
        ('d-e','d1','e1',[(364,104),(376,104),(376,80),(389,80)]),
        ('d-f','d1','f1',[(364,104),(376,104),(376,126),(389,126)]),
        ('e-d','e1','d2',[(425,80),(437,80),(437,104),(449,104)]),
        ('f-d','f1','d2',[(425,126),(437,126),(437,104),(449,104)]),
    ]
    for ident,s,t,p in paths: edge(ident,p,source=s,target=t)

    # Left: accepted token histories and the request-submission path.
    # Four history fields use two rows, preserving the final printed type size.
    shape('history','',6,164,229,86,fill='#FFFFFF',stroke='#9AAEB9')
    text('history-label','Accepted histories',10,165,221,26)
    fields=[('role','Role/task',13,196,103),('tokens','Model text',118,196,110),
            ('tools','Tool result',13,222,103),('peer','Agent out.',118,222,110)]
    for ident,value,x,y,w in fields:
        shape('history-'+ident,value,x,y,w,25,fill='#F2F5F7',stroke='#A9B5BF',extra='rounded=0;')
    text('input-label','B2 input',6,253,110,26,bold=True,extra='align=left;')
    shape('input-prefix','Prefix\nreuse KV',6,282,115,50,fill=PALE,stroke=BLUE,extra='rounded=0;')
    shape('input-suffix','New tokens\nprefill',121,282,114,50,fill=WARM,stroke=AMBER,extra='rounded=0;')
    edge('build-request',[(121,250),(121,282)],source='history',exit_xy=(115/229,1),
         target='input-prefix',entry_xy=(1,0),color=BLUE)
    edge('input-to-ready',[(121,332),(121,347)],color=BLUE)
    shape('ready-queue','',6,347,229,80,fill='#FFFFFF',stroke='#A7B4BD')
    text('ready-title','Ready requests',11,349,218,24,extra='align=left;')
    for ident,value,x,y,wf in [('rq-b','W1:B2',13,376,1),('rq-c','W1:C1',121,376,1),
                              ('rq-e','W2:E1',13,400,2),('rq-f','W2:F1',121,400,2)]:
        shape(ident,value,x,y,107,24,fill=PALE if wf==1 else LILAC,
              stroke=BLUE if wf==1 else PURPLE,extra='rounded=0;')
    edge('queue-to-scheduler',[(121,427),(121,444)],color=BLUE)
    shape('scheduler','',6,444,229,55,fill='#F1F4F6')
    text('scheduler-name','Serving scheduler',10,445,221,26,bold=True)
    text('scheduler-mode','Prefill / decode',10,471,221,24)

    # Right: vertically paired workers. Both ranks expose the same kinds of
    # local state; shared wording is moved to the caption, not smaller type.
    for wi,oy,agents in [(0,164,('B','E')),(1,342,('C','F'))]:
        w=f'worker{wi}'
        shape(w,'',264,oy,230,157,stroke=EDGE,extra='dashed=1;dashPattern=5 4;')
        text(w+'-title',f'Worker {wi} (TP2)',268,oy+1,222,27,bold=True)
        for rank,rx in [(0,273),(1,384)]:
            r=f'{w}-rank{rank}'
            shape(r,'',rx,oy+31,101,120,fill='#F6F7F8',stroke='#A0AFB9')
            text(r+'-name',f'Rank {rank}',rx+1,oy+31,99,24)
            shape(r+'-weights','Weights',rx+6,oy+56,89,24,fill='#E3E8EB',stroke='#8798A3',extra='rounded=0;')
            for ai,agent in enumerate(agents):
                y=oy+82+ai*23
                text(r+f'-agent-{agent}',agent,rx+4,y,23,22,bold=True)
                # Two illustrative layers by three token blocks. Each rank
                # holds its own local shard at these same token positions.
                for layer in range(2):
                    for block in range(3):
                        shape(r+f'-{agent}-l{layer}-b{block}','',rx+31+block*18,y+3+layer*9,
                              16,7,fill=WARM if block==2 else (PALE if ai==0 else LILAC),
                              stroke=AMBER if block==2 else (BLUE if ai==0 else PURPLE),
                              extra='rounded=0;strokeWidth=1;')
            text(r+'-table','KV table',rx+1,oy+127,99,24)
        # Request dispatch shares an inner bus; accepted results use the outer
        # bus, so opposite directions do not cross through the rank contents.
        edge(f'dispatch{wi}',[(235,464),(246,464),(246,oy+29),(264,oy+29)],color=BLUE,
             source='scheduler',exit_xy=(1,20/55),target=w,entry_xy=(0,29/157))
    edge('accepted-outputs',[(494,371),(506,371),(506,156),(121,156),(121,164)],dashed=True,
         source='worker1',exit_xy=(1,29/157),target='history',entry_xy=(115/229,0))
    edge('result0',[(494,193),(506,193)],dashed=True,arrow='none',
         source='worker0',exit_xy=(1,29/157))
    text('kv-semantics','KV: layers × blocks; rightmost = new',6,506,508,27)

    path.parent.mkdir(parents=True,exist_ok=True)
    ET.indent(mx)
    ET.ElementTree(mx).write(path,encoding='utf-8',xml_declaration=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    build(p.parse_args().output)
