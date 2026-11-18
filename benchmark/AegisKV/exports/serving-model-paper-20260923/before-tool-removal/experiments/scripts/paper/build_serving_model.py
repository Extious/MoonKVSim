#!/usr/bin/env python3
"""Single-column serving overview: DAGs, mixed requests and TP-local KV.

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
PALE = '#D9EAF3'
PURPLE = '#77638B'
LILAC = '#E8DEF0'
AMBER = '#A27943'
WARM = '#F3CE86'
WIDTH, HEIGHT = 520, 560


def build(path: Path) -> None:
    mx = ET.Element('mxfile', host='app.diagrams.net', type='device')
    diagram = ET.SubElement(mx, 'diagram', id='serving-model', name='Workflow serving and TP KV')
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
    shape('workflow1','',6,32,306,116,fill='#F2F8FB',stroke=BLUE)
    shape('workflow2','',320,32,186,116,fill='#F7F3FA',stroke=PURPLE)
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

    # Accepted histories and a compact mixed-workflow dispatch path.
    shape('history','',26,162,468,51,fill='#F1F4F6',stroke='#9AAEB9')
    text('history-label','Accepted histories',30,163,460,25,bold=True)
    text('history-content','tokens + tool results',30,187,460,25)
    edge('history-to-ready',[(260,213),(260,219)],arrow='none')
    text('ready-title','Ready requests',150,219,220,26)
    text('dispatch0-label','B2, E1',56,246,144,25)
    text('dispatch1-label','C1, F1',308,246,144,25)
    edge('dispatch-bus',[(260,245),(260,273)],arrow='none')

    def hatch(ident,x,y,w,h):
        # Redundant encoding makes the new suffix distinguishable in grayscale.
        for i in range(1,int(w/7)+1):
            xx=x+i*7
            if xx<=x+w:
                edge(f'{ident}-{i}',[(max(x,xx-6),y+h),(xx,y)],
                     arrow='none',color=AMBER)

    # The eight-head MHA example is scoped in the caption. Each worker is a
    # complete replica, with complementary head shards across its TP ranks.
    for wi,wx,agents in [(0,8,('B','E')),(1,260,('C','F'))]:
        worker=f'worker{wi}'
        shape(worker,'',wx,278,244,218,fill='#FAFBFC',stroke=EDGE)
        text(worker+'-title',f'Worker {wi} (TP=2)',wx+4,280,236,28,bold=True)
        edge(f'dispatch{wi}',[(260,273),(wx+122,273),(wx+122,278)],
             target=worker,entry_xy=(.5,0))
        for rank,rx in [(0,wx+4),(1,wx+125)]:
            r=f'{worker}-rank{rank}'
            shape(r,'',rx,310,115,182,fill='#FFFFFF',stroke='#A0AFB9')
            text(r+'-name',f'Rank {rank}',rx+1,311,113,25,bold=True)
            text(r+'-head-label','Q/KV',rx+1,337,113,24)
            text(r+'-head-range','heads 0–3' if rank==0 else 'heads 4–7',rx+1,361,113,24)
            for ai,agent in enumerate(agents):
                group_y=386+ai*51
                color,fill=(BLUE,PALE) if ai==0 else (PURPLE,LILAC)
                text(r+f'-agent-{agent}',agent,rx+2,group_y+2,23,47,bold=True)
                for ki,kind in enumerate(('K','V')):
                    ty=group_y+ki*23
                    text(r+f'-{agent}-{kind}-label',kind,rx+23,ty,23,24)
                    bx,by,bw,bh=rx+47,ty+6,62,12
                    ident=r+f'-{agent}-{kind}'
                    # K and V cover identical schematic token positions. The
                    # complete four-head shard is represented by each bar.
                    if agent=='B':
                        shape(ident+'-prefix','',bx,by,40,bh,fill=fill,stroke=color,
                              extra='rounded=0;strokeWidth=1;')
                        shape(ident+'-new','',bx+40,by,bw-40,bh,fill=WARM,stroke=AMBER,
                              extra='rounded=0;strokeWidth=1;')
                        hatch(ident+'-hatch',bx+40,by,bw-40,bh)
                    else:
                        shape(ident,'',bx,by,bw,bh,fill=fill,stroke=color,
                              extra='rounded=0;strokeWidth=1;')

    # Full-worker outputs return outside the rank containers; internal
    # attention and collective communication are intentionally caption-only.
    edge('result0',[(8,386),(1,386),(1,187),(26,187)],dashed=True,
         source='worker0',exit_xy=(0,108/218),target='history',entry_xy=(0,25/51))
    edge('result1',[(504,386),(517,386),(517,187),(494,187)],dashed=True,
         source='worker1',exit_xy=(1,108/218),target='history',entry_xy=(1,25/51))
    text('token-direction','tokens',188,501,80,25)
    edge('token-direction-arrow',[(272,514),(330,514)])
    text('reuse-turns','B1→B2:',40,531,91,25)
    shape('reuse-swatch','',139,537,24,14,fill=PALE,stroke=BLUE,extra='rounded=0;')
    text('reuse-label','Reused',168,531,80,25,extra='align=left;')
    shape('new-swatch','',269,537,24,14,fill=WARM,stroke=AMBER,extra='rounded=0;')
    hatch('new-swatch-hatch',269,537,24,14)
    text('new-label','New tokens',300,531,163,25,extra='align=left;')

    path.parent.mkdir(parents=True,exist_ok=True)
    ET.indent(mx)
    ET.ElementTree(mx).write(path,encoding='utf-8',xml_declaration=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    build(p.parse_args().output)
