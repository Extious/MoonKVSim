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
WIDTH, HEIGHT = 520, 528
RUNTIME_HEIGHT = 176
ROUTER_Y = 182
WORKER_Y = 244


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
             exit_xy=(1,.5), entry_xy=(0,.5), route_points=False):
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
        if (route_points and points) or len(points)>2:
            arr = ET.SubElement(geom, 'Array', **{'as':'points'})
            # Attached DAG routes contain only intermediate bends; the other
            # routes include their source/target coordinates at both ends.
            bends = points if route_points else points[1:-1]
            for x,y in bends: ET.SubElement(arr, 'mxPoint', x=str(x), y=str(y))

    shape('canvas','',0,0,WIDTH,HEIGHT,stroke='none',extra='rounded=0;')
    shape('runtime','',8,0,504,RUNTIME_HEIGHT,fill=GRAY,stroke=EDGE)
    text('runtime-title','Workflow runtime',8,2,504,28,size=23.5,bold=True)
    # Only replace the workflow content in the established runtime/Router/TP drawing.
    # Nodes here are whole Agent tasks; calls stay internal to their Agent.
    shape('workflow','',12,34,496,136,fill='#FFFFFF',stroke=EDGE)
    # Planar left-to-right layout: C/A/B roots, E/D local joins, then F/G.
    # Every route uses explicit bend points and distinct merge ports. The
    # B->F cross-level dependency stays in its own bottom lane.
    nodes=[('c','C',32,40),('a','A',32,80),('b','B',32,120),
           ('e','E',188,40),('d','D',188,104),('f','F',316,104),('g','G',444,72)]
    for ident,value,x,y in nodes:
        shape(ident,value,x,y,44,32,fill=MINT,stroke=TEAL,extra='arcSize=15;')
    paths=[
      ('a-d','a','d',[(132,104),(132,112)],(1,.75),(0,.25)),
      ('b-d','b','d',[],(1,.25),(0,.75)),
      ('a-e','a','e',[(132,88),(132,64)],(1,.25),(0,.75)),
      ('c-e','c','e',[],(1,.5),(0,.5)),
      ('b-f','b','f',[(54,164),(292,164),(292,129.6)],(.5,1),(0,.8)),
      ('d-f','d','f',[],(1,.5),(0,.5)),
      ('e-g','e','g',[(404,56),(404,80)],(1,.5),(0,.25)),
      ('f-g','f','g',[(404,120),(404,96)],(1,.5),(0,.75))]
    for ident,s,t,points,ex,en in paths:
        edge(ident,points,source=s,target=t,exit_xy=ex,entry_xy=en,route_points=True)

    # The runtime submits ready invocations directly to the Router.
    shape('router','Router',194,ROUTER_Y,132,32,fill=ROUTER_FILL,stroke=BLUE,bold=True)
    edge('ready-to-router',[(260,RUNTIME_HEIGHT),(260,ROUTER_Y)],source='runtime',target='router',
         exit_xy=(.5,1),entry_xy=(.5,0),color=INK)
    text('dispatch0-label','A4, C4',28,ROUTER_Y+34,108,25)
    text('dispatch1-label','B2',400,ROUTER_Y+34,80,25)

    def hatch(ident,x,y,w,h):
        # Redundant encoding makes the new suffix distinguishable in grayscale.
        for i in range(1,int(w/7)+1):
            xx=x+i*7
            if xx<=x+w:
                edge(f'{ident}-{i}',[(max(x,xx-6),y+h),(xx,y)],
                     arrow='none',color=AMBER)

    # Latest repeated turn of each Agent. Reused width grows with earlier
    # invocations; the hatched suffix is that turn's new KV.
    latest = [('A4',32,18),('C4',44,18),('B2',16,18)]
    # The eight-head MHA example is scoped in the caption. Each worker is a
    # complete replica, with complementary head shards across its TP ranks.
    for wi,wx,agents in [(0,8,latest[:2]),(1,260,latest[2:])]:
        dy=WORKER_Y-278
        worker=f'worker{wi}'
        shape(worker,'',wx,WORKER_Y,244,218,fill=ENGINE_FILL,stroke=EDGE)
        text(worker+'-title',f'Worker {wi} (TP=2)',wx+4,280+dy,236,28,bold=True)
        edge(f'dispatch{wi}',[(194 if wi==0 else 326,ROUTER_Y+16),(wx+122,ROUTER_Y+16),(wx+122,WORKER_Y)],
             source='router',exit_xy=(0 if wi==0 else 1,.5),
             target=worker,entry_xy=(.5,0),color=INK)
        for rank,rx in [(0,wx+4),(1,wx+125)]:
            r=f'{worker}-rank{rank}'
            shape(r,'',rx,310+dy,115,182,fill='#FFFFFF',stroke=EDGE)
            text(r+'-name',f'Rank {rank}',rx+1,311+dy,113,25,bold=True)
            text(r+'-head-label','Q/KV',rx+1,337+dy,113,24)
            text(r+'-head-range','heads 0–3' if rank==0 else 'heads 4–7',rx+1,361+dy,113,24)
            for ai,(agent,reused,new) in enumerate(agents):
                group_y=386+dy+(26 if len(agents)==1 else 0)+ai*51
                text(r+f'-agent-{agent}',agent,rx+1,group_y+2,32,47,size=22.6,bold=True)
                for ki,kind in enumerate(('K','V')):
                    ty=group_y+ki*23
                    text(r+f'-{agent}-{kind}-label',kind,rx+34,ty,16,24,size=22.6)
                    bx,by,bh=rx+50,ty+6,12
                    ident=r+f'-{agent}-{kind}'
                    # K and V cover identical schematic token positions. The
                    # complete four-head shard is represented by each bar.
                    shape(ident+'-prefix','',bx,by,reused,bh,fill=MINT,stroke=TEAL,
                          extra='rounded=0;strokeWidth=1;')
                    shape(ident+'-new','',bx+reused,by,new,bh,fill=WARM,stroke=AMBER,
                          extra='rounded=0;strokeWidth=1;')
                    hatch(ident+'-hatch',bx+reused,by,new,bh)

    # Full-worker outputs return outside the rank containers; internal
    # attention and collective communication are intentionally caption-only.
    return_y = RUNTIME_HEIGHT-8
    edge('result0',[(8,WORKER_Y+28),(1,WORKER_Y+28),(1,return_y),(8,return_y)],dashed=True,
         source='worker0',exit_xy=(0,28/218),target='runtime',entry_xy=(0,return_y/RUNTIME_HEIGHT))
    edge('result1',[(504,WORKER_Y+28),(517,WORKER_Y+28),(517,return_y),(512,return_y)],dashed=True,
         source='worker1',exit_xy=(1,28/218),target='runtime',entry_xy=(1,return_y/RUNTIME_HEIGHT))
    dy=WORKER_Y-278
    text('token-direction','tokens',188,501+dy,80,25)
    edge('token-direction-arrow',[(272,514+dy),(330,514+dy)])
    shape('reuse-swatch','',68,537+dy,24,14,fill=MINT,stroke=TEAL,extra='rounded=0;')
    text('reuse-label','Reused KV',98,531+dy,130,25,extra='align=left;')
    shape('new-swatch','',268,537+dy,24,14,fill=WARM,stroke=AMBER,extra='rounded=0;')
    hatch('new-swatch-hatch',268,537+dy,24,14)
    text('new-label','New KV',298,531+dy,140,25,extra='align=left;')

    path.parent.mkdir(parents=True,exist_ok=True)
    ET.indent(mx)
    ET.ElementTree(mx).write(path,encoding='utf-8',xml_declaration=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    build(p.parse_args().output)
