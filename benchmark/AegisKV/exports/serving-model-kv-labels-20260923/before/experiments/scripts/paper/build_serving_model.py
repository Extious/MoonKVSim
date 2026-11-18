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
# Shared with the current System Overview's native Draw.io source.
EDGE = '#70808A'
TEAL = '#39756A'
MINT = '#E1EEE8'
BLUE = '#23688D'
PALE_BLUE = '#DDEBF3'
ROUTER_FILL = '#DDE5EF'
GRAY = '#F1F3F4'
ENGINE_FILL = '#F4F5F1'
AMBER = '#9B6428'
WARM = '#F3E5D1'
WIDTH, HEIGHT = 520, 576
WORKER_Y = 294


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
        style = (f'rounded=1;arcSize=6;whiteSpace=wrap;html=0;'
                 f'fontFamily={FONT};fontSize={size};fontColor={INK};fontStyle={int(bold)};'
                 f'align=center;verticalAlign=middle;fillColor={fill};strokeColor={stroke};'
                 f'strokeWidth=1.0;spacing=1;{extra}')
        cell = ET.SubElement(root, 'mxCell', id=ident, value=value, style=style, vertex='1', parent='1')
        ET.SubElement(cell, 'mxGeometry', x=str(x), y=str(y), width=str(w), height=str(h),
                      **{'as':'geometry'})

    def text(ident, value, x, y, w, h, **kwargs):
        shape(ident, value, x, y, w, h, fill='none', stroke='none', **kwargs)

    def edge(ident, points, *, dashed=False, arrow='block', color=EDGE, source=None, target=None,
             exit_xy=(1,.5), entry_xy=(0,.5)):
        style = (f'rounded=0;html=0;strokeColor={color};strokeWidth=1.4;'
                 f'endArrow={arrow};endSize=4;endFill=1;dashed={int(dashed)};dashPattern=4 3;')
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
    shape('runtime','',8,0,504,220,fill=GRAY,stroke=EDGE)
    text('runtime-title','Workflow runtime',20,2,480,28,size=23.5,bold=True,extra='align=left;')
    shape('workflow1','',16,34,236,122,fill='#FFFFFF',stroke=EDGE)
    shape('workflow2','',268,34,236,122,fill='#FFFFFF',stroke=EDGE)
    text('wf1-title','Workflow 1',20,35,228,26,bold=True)
    text('wf2-title','Workflow 2',272,35,228,26,bold=True)
    # The graph depicts invocation dependencies, not elapsed time.
    nodes = [
        ('a1','A1',32,93,34,32,MINT,TEAL),
        ('b1','B1',88,70,34,32,MINT,TEAL),
        ('b2','B2',144,70,34,32,MINT,TEAL),
        ('c1','C1',116,116,34,32,MINT,TEAL),
        ('a2','A2',200,93,34,32,MINT,TEAL),
        ('d1','D1',284,93,34,32,PALE_BLUE,BLUE),
        ('e1','E1',368,70,34,32,PALE_BLUE,BLUE),
        ('f1','F1',368,116,34,32,PALE_BLUE,BLUE),
        ('d2','D2',452,93,34,32,PALE_BLUE,BLUE),
    ]
    for ident,value,x,y,w,h,fill,stroke in nodes:
        shape(ident,value,x,y,w,h,fill=fill,stroke=stroke)
    paths = [
        ('a-b','a1','b1',[(66,101),(88,86)],(1,.25),(0,.5)),
        ('a-c','a1','c1',[(66,117),(116,132)],(1,.75),(0,.5)),
        ('b1-b2','b1','b2',[(122,86),(144,86)],(1,.5),(0,.5)),
        ('b2-a','b2','a2',[(178,86),(200,101)],(1,.5),(0,.25)),
        ('c-a','c1','a2',[(150,132),(200,117)],(1,.5),(0,.75)),
        ('d-e','d1','e1',[(318,101),(368,86)],(1,.25),(0,.5)),
        ('d-f','d1','f1',[(318,117),(368,132)],(1,.75),(0,.5)),
        ('e-d','e1','d2',[(402,86),(452,101)],(1,.5),(0,.25)),
        ('f-d','f1','d2',[(402,132),(452,117)],(1,.5),(0,.75)),
    ]
    for ident,s,t,p,ex,en in paths:
        edge(ident,p,source=s,target=t,exit_xy=ex,entry_xy=en)

    # Accepted histories and a compact mixed-workflow dispatch path.
    shape('history','',30,164,460,50,fill='#FFFFFF',stroke=EDGE)
    text('history-label','Accepted histories',34,165,452,25,bold=True)
    text('history-content','tokens + tool results',34,189,452,25)
    shape('router','Router',194,232,132,32,fill=ROUTER_FILL,stroke=BLUE,bold=True)
    edge('ready-to-router',[(260,214),(260,232)],source='history',target='router',
         exit_xy=(.5,1),entry_xy=(.5,0),color=INK)
    text('dispatch0-label','B2, E1',36,266,88,25)
    text('dispatch1-label','C1, F1',388,266,100,25)

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
        dy=WORKER_Y-278
        worker=f'worker{wi}'
        shape(worker,'',wx,WORKER_Y,244,218,fill=ENGINE_FILL,stroke=EDGE)
        text(worker+'-title',f'Worker {wi} (TP=2)',wx+4,280+dy,236,28,bold=True)
        edge(f'dispatch{wi}',[(194 if wi==0 else 326,248),(wx+122,248),(wx+122,WORKER_Y)],
             source='router',exit_xy=(0 if wi==0 else 1,.5),
             target=worker,entry_xy=(.5,0),color=INK)
        for rank,rx in [(0,wx+4),(1,wx+125)]:
            r=f'{worker}-rank{rank}'
            shape(r,'',rx,310+dy,115,182,fill='#FFFFFF',stroke=EDGE)
            text(r+'-name',f'Rank {rank}',rx+1,311+dy,113,25,bold=True)
            text(r+'-head-label','Q/KV',rx+1,337+dy,113,24)
            text(r+'-head-range','heads 0–3' if rank==0 else 'heads 4–7',rx+1,361+dy,113,24)
            for ai,agent in enumerate(agents):
                group_y=386+dy+ai*51
                color,fill=(TEAL,MINT) if ai==0 else (BLUE,PALE_BLUE)
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
    edge('result0',[(8,WORKER_Y+28),(1,WORKER_Y+28),(1,189),(30,189)],dashed=True,
         source='worker0',exit_xy=(0,28/218),target='history',entry_xy=(0,.5))
    edge('result1',[(504,WORKER_Y+28),(517,WORKER_Y+28),(517,189),(490,189)],dashed=True,
         source='worker1',exit_xy=(1,28/218),target='history',entry_xy=(1,.5))
    dy=WORKER_Y-278
    text('token-direction','tokens',188,501+dy,80,25)
    edge('token-direction-arrow',[(272,514+dy),(330,514+dy)])
    text('reuse-turns','B1→B2:',40,531+dy,91,25)
    shape('reuse-swatch','',139,537+dy,24,14,fill=MINT,stroke=TEAL,extra='rounded=0;')
    text('reuse-label','Reused',168,531+dy,80,25,extra='align=left;')
    shape('new-swatch','',269,537+dy,24,14,fill=WARM,stroke=AMBER,extra='rounded=0;')
    hatch('new-swatch-hatch',269,537+dy,24,14)
    text('new-label','New tokens',300,531+dy,163,25,extra='align=left;')

    path.parent.mkdir(parents=True,exist_ok=True)
    ET.indent(mx)
    ET.ElementTree(mx).write(path,encoding='utf-8',xml_declaration=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    build(p.parse_args().output)
